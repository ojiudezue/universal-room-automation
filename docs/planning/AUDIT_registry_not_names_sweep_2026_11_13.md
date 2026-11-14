# AUDIT: Registry, never name guessing — house-wide sweep (card REGISTRY-NOT-NAMES-1)

Run 2026-11-13 20:07 CDT (`date`), read-only, by ura-prober. Tree: develop @ 0a2fc460 (`custom_components/universal_room_automation/`, all .py,
frontend excluded). Live data: `/Users/okosisi/ha-config/.storage/core.{entity,device,config_entries}_registry`, `person`, `core.area_registry`
(read-only, parsed with `python3 -I`; no secrets read).

NOT done: I did not read `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` or `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` completely (this is a code-pattern
sweep, not an HVAC/presence diagnosis). Cluster 5 (hvac_fans occupied guard) and cluster 4 (BLE/Bermuda) migrations MUST have their builders read
those docs first. Sweep is by grep + a throwaway AST scan (prototype counts in §7); it will miss guesses hidden behind helpers I did not follow.
Treat counts as a floor.

## 1. Answer

Rough-grep "~99 sites" on the card is an undercount of surface but the real population is small in distinct decisions. A throwaway AST scan finds
171 raw pattern hits (64 f-string domain ids, 51 `lower().replace(" ","_")` slugs, 34 `endswith("_suffix")`, 17 `split(".",1)[1]`, 5 `"_x" in`);
they reduce to **8 clusters / ~45 distinct decision sites**. Three clusters are already owned (NVR family, person slug rule). **Three live
defects were found that no existing card owns** (cluster 5 room slug, cluster 4 BLE person match, cluster 6 lock proximity), each proven against
the live registry (§2). One structural fact changes the NVR plan: **Frigate and Protect devices cannot be paired by registry alone** (§3).

## 2. Live evidence (what decides risk)

| # | Observation (source) | Meaning |
|---|---|---|
| L1 | 11 of 47 URA rooms: real `binary_sensor.*_occupied` != `binary_sensor.<slug(room_name)>_occupied` (registry vs `room_name`; e.g. Foyer -> `binary_sensor.foyer_foyer_occupied`, Jaya Bedroom -> `..._jaya_bedroom_bedroom_4_occupied`, Guest Bedroom 2 -> `binary_sensor.upstairs_guest_bedroom_occupied`, Media -> `media_room_occupied`) | slug-built own-entity ids miss 23% of rooms |
| L2 | `sensor.bermuda_*` per-person: 0 entities (registry); real names are `sensor.iphone_oji_distance_to_*` (114 for Oji), `sensor.ezinne_iphone_...` | `aggregation.py:6179-6186` finds 0 sensors for every person |
| L3 | `person_coordinator._calculate_confidence` match `"oji_udezue" in eid or "ojiudezue" in eid`: 0 of 456 Bermuda distance sensors for Oji (his are `iphone_oji_*`); 126 each for Ezinne, Ziri, Jaya (registry) | Oji always falls to the fixed 0.5 / no `closest_distance` |
| L4 | `.storage/person` lists per-person `device_trackers` (Oji: `private_ble_device_8ce182`, Jaya `private_ble_device_249050`, Ezinne `zinny_s_iphone_15`); none of those ids contain the person name | `_find_bermuda_area_sensor` Strategy 2 (`first_name in entity_id`) cannot match private_ble trackers; the registry fact exists and is unused |
| L5 | 48 URA-OWNED entities `binary_sensor.<room>_camera_person_detected` (platform universal_room_automation) end in `_person_detected`; 19 real unifiprotect ones do | any suffix test for Protect also matches URA's fused room sensors |
| L6 | Frigate person sensors: 36, all one config entry; entity_id stem == unique_id camera name (case-folded) in 36/36; 17/36 carry `_2` (`unique_id` `01KM..:occupancy_sensor:<cam>_person`) | the stem guess happens to be right today; `unique_id`/device identifier give the exact name |
| L7 | Frigate devices 37: 0 have `connections`; Protect devices carry `("mac", ...)`; Frigate identifier `("frigate","<entry>:<object>")` | no registry join exists between a Frigate camera and its Protect twin (see §3) |
| L8 | `camera.garage_a_2` platform frigate beside `camera.garage_a_{high,medium,low}_resolution_channel` platform unifiprotect | the known `_2` pairing hazard is live |
| L9 | Span: 38 `_power` circuit sensors passing the discovery filter; 1 mislabelled by `"_2" in entity_id` (`sensor.span_panel_ac_2_power` is on device "Span Right", labelled left) | name guess of panel, low impact |
| L10 | Proximity: `sensor.madronehaos_<person>_distance` x4 + `_nearest_distance`, platform proximity | works today only by naming convention |
| L11 | 11 of 47 room names do not equal any HA area name (area_registry) | area-name == room-name strategies miss those rooms; room entries DO store `area_id` (47 rooms, `area_id` key) |

## 3. Structural finding: the cross-NVR camera pairing is not a registry fact

Registry gives, exactly: entity `platform`, `device_id`, `unique_id`, `translation_key`/`original_device_class`, config entry (host), and for Frigate the
object name via device identifier (`camera_resolver.py:626, :1528` already reads it) or `unique_id`. It does NOT give "this Frigate camera and this
Protect camera are the same physical camera" (L7). Today that join is a name-stem equality (`camera_census.py:940-1000`, `transit_validator.py:1465`,
`perimeter_alert.py:2400-2480`, `camera_resolver.py:640-700` dstem index, `const.py:3254 EXTERIOR_CAMERA_KEY_ALIASES`). Rule consequence: the only
non-guess answer is an explicit, operator-visible pairing table (or evidence-gated join per `PLANNING_nvr_witness_layer.md` §5 W1: Frigate object name
from device identifier + uniqueness conditions) behind ONE resolver function. The guard (§6) must allowlist exactly that one function.

## 4. Cluster table (ranked by consumer class, then live risk)

Class: SEC = trust/security, NOTIF = notification, COMFORT, DISPLAY. Status: OWN (allowed), MIGRATE, COVERED.

| Rank | Cluster | Sites | Status | Consumer | Live risk | Known bug / ledger |
|---|---|---|---|---|---|---|
| 1 | C1 NVR family / platform from suffix | ~16 | COVERED (NVR-WITNESS W2/W5b/W5c) with two gaps | SEC (perimeter demote, transit 0.9 vs 0.8), COMFORT (fan veto agreement), census | HIGH: garage_a leg 0/71 | garage_a `_2` pairing (memory feedback_registry_not_name_guessing; plan §5) |
| 2 | C6 Person id from proximity sensor name | 2 | MIGRATE (NEW, uncarded) | SEC (lock regime lockout/approach) | MED: works by convention | none known |
| 3 | C4 Person identity strings (BLE tracker, Bermuda sensors, face names) | ~14 | PARTLY COVERED (slug rule only); registry fixes NEW | SEC-adjacent (census identified set, egress BLE leg), COMFORT (music following, room location) | HIGH: L2-L4 live | music following display-name mismatch; AI rule person filter; census residuals A-D |
| 4 | C2 Camera stem / cross-NVR pairing | ~14 | MIGRATE with explicit pairing table (W1 covers garage_a only) | SEC, census, perimeter | HIGH | garage_a; interior cams filed exterior by name (memory) |
| 5 | C5 Room slug -> own entity ids / area-name == room-name | ~20 | MIGRATE (NEW, uncarded); precedent exists | COMFORT (HVAC fan occupied guard), memory/NM conditioning, music following | HIGH: 11/47 rooms miss (L1) | v5.51.0 M-1 (Ziri bedroom guard blind; only punctuation fixed, `memory_facade.py:252-255`), ROOM-SWITCH-LOOKUP-BY-NAME-1 (2026-10-10, switches only) |
| 6 | C3 Frigate sibling sensors by name (person_count, face name) | ~12 | MIGRATE (partly done by FACE-SOURCE-REGISTRY-DISCOVERY-1) | SEC-adjacent (census counts, face identity) | MED: registry-first already | CENSUS-SUFFIX-FIX 2026-08-15 (all `_2` dropped, census pinned) |
| 7 | C7 Entity kind / location / panel from name | ~9 | MIGRATE or make fallback counted | NOTIF (safety location), COMFORT, DISPLAY | LOW-MED | none known |
| 8 | C8 UI prefill / display names | ~8 | OWN / allowed | DISPLAY | LOW | none |

## 5. Per-cluster site detail

### C1 NVR family / platform from suffix (COVERED by NVR-WITNESS-CONSOLIDATION-1 unless noted)
| file:line | infers | class | consumer | note |
|---|---|---|---|---|
| `transit_validator.py:2689-2713` `_count_platforms_fired`: `"_person_occupancy" in entity_id` -> frigate, `"_person_detected"` -> unifi, else entity_id | platform | COVERED W2 | SEC (crossing confidence 0.9 vs 0.8) | fallback path treats an unclassified entity as its own platform, so two legs of one NVR can count as 2 platforms |
| `perimeter_alert.py:578-583` `_leg_tag` | leg engine | COVERED W2 | SEC (feeds every gate) | `engine_by_leg` then drives `nvr_family` (`perimeter_fp_gates.py:25`) |
| `perimeter_alert.py:623-631, :656-658, :671, :708, :723` base_engine, `_e2`, `_zs.endswith("_2")` | engine / host | COVERED W2 | SEC | `:723` guesses Frigate host from `_2` for zone legs |
| `perimeter_alert.py:4525-4528` `_is_frigate_person_entity` | is Frigate | COVERED W2 | SEC | |
| `perimeter_alert.py:2179-2205` Frigate cam name for snapshot URL/event cache from sensor stem | camera name | MIGRATE (not in plan table): Frigate object name from device identifier / unique_id | NOTIF (snapshot in alert) | wrong stem = no event snapshot |
| `camera_census.py:635-649` (`_person_occupancy` -> FRIGATE with NO platform check; `_person_detected` + unknown platform -> UNIFI) | platform | COVERED W5b | SEC (census counts, family vote) | URA-owned `*_camera_person_detected` (L5) would hit the UniFi default if ever in scope |
| `camera_census.py:985-990, :1142-1143, :1171` | platform | COVERED W5b | census | |
| `camera_census.py:3440-3445` engine `f"{hint}2" if endswith("_2")` | engine / host | MIGRATE: `resolver._engine_tag` already exists, the suffix branch is the error path; make it counted | SEC-adjacent | |
| `binary_sensor.py:1827-1860` room fusion `on_integrations` | agreement class | COVERED W5c | COMFORT (fan veto) | |
| `camera_census.py:652` `"person" in bs_entity.name.lower()` for Reolink/Dahua | is person sensor | MIGRATE: `translation_key in ("person","smart_motion_human")` (live: reolink `translation_key=person`, dahua `smart_motion_human`) | census | |
| `camera_resolver.py:213-219,_has_any_suffix*` | which entity is the person sensor | plan says KEEP (slot pick). Disagree in part: Protect/Reolink/Dahua expose `translation_key` (L-section probe), Frigate `unique_id` `...:occupancy_sensor:<cam>_person`. Replace the suffix vocabulary with those two registry fields | census/perimeter | verify in W0 |

### C2 Camera stem / cross-NVR pairing
| file:line | infers | class | consumer | note |
|---|---|---|---|---|
| `camera_census.py:1009-1042` `_extract_camera_stem` (also called `transit_validator.py:1186,1189,1465,1589,1605,2118,2421,2682,2699`) | camera identity | MIGRATE: `canonical_camera_key` (`camera_resolver.py:460`) from device_id / resolver; stem only through the one pairing resolver | SEC | strips `_N` then suffix: two different cameras can collapse (`camera_resolver` A-MED-2 guard exists for this) |
| `camera_census.py:940-1000` sibling probe `f"binary_sensor.{stem}_person_detected"` etc. then `ent_reg.async_get(candidate)` | pairing + platform (`endswith` at :985) | MIGRATE to the pairing resolver | census | existence in registry != same camera |
| `perimeter_alert.py:2250-2290` `_strip_person_family_suffixes` / `_camera_key_for_sensor` | camera key | MIGRATE (registry `device_id` -> `canonical_camera_key`) | SEC (cooldown, in-flight, dedup keyed by it) | |
| `perimeter_alert.py:2400-2480` legacy fallback builds `f"{base_bs}_2"`, `_person_detected[_2]`, alias table | pairing | OWN as a counted kill-switch fallback ONLY; today uncounted | SEC | `EXTERIOR_CAMERA_KEY_ALIASES` (`const.py:3254`) = hand table (operator-visible, acceptable form of pairing table) |
| `perimeter_alert.py:5318` `_near_areas` rebuilds `binary_sensor.{stem}_person_detected` | camera key | MIGRATE | SEC (arrival near-areas) | |
| `camera_resolver.py:640-700` stem index + dstem | device grouping by stem | KEEP-but-bounded: A-MED-2 uniqueness guard; subject of W1 | SEC | |
| `domain_coordinators/optimization.py:2653-2655, :3303-3305` `binary_sensor.{cam.split('.')[1]}_person_occupancy[_2]` from a configured `camera.*` | which sensors belong to the camera | MIGRATE: resolver legs by device_id | COMFORT/optimizer exclusion set | wrong for Protect cameras (`camera.garage_a_*` -> no such sensor) |
| `const.py:3254` `EXTERIOR_CAMERA_KEY_ALIASES` | alias | OWN (explicit table), move under pairing resolver | | |

### C3 Frigate sibling sensors by name (person_count, face name)
| file:line | infers | class | consumer | note |
|---|---|---|---|---|
| `camera_census.py:672-690, :1150-1165` `sensor.{base}_person_count` + fallback scan `endswith("_person_count")` on device sensors | person_count entity | MIGRATE: same `device_id` + `unique_id` token `:sensor_object_count:<cam>_person` (L-probe: `01KM..:sensor_object_count:master_hallway_person`) | SEC-adjacent (census numeric) | device scope already used for the fallback |
| `camera_census.py:3192-3193, :3361-3368, :3538-3550` | face-name sensor ids | COVERED-PARTIAL: FACE-SOURCE-REGISTRY-DISCOVERY-1 registry-first (`_registry_face_candidates_for_stem`), built ids on empty registry, counted in `_face_source_pattern_fallback_stems`. Remaining: Protect `_face_recognized` names are "dead until D1-PROTECT-FACE-BRIDGE" (documented) | census/identity | compliant pattern: registry-first + counted fallback |
| `camera_census.py:3794-3838, :6000-6012` `endswith("_person_occupancy")` gates face lookup; non-matching go to device join (`:6000`) | gate | MIGRATE: always device-join; drop the suffix gate | SEC-adjacent | CENSUS-SUFFIX-FIX history |
| `camera_census.py:3675-3711` `sensor.frigate_` prefix / `_last_camera_2` (kill-switch-off path only; live path reads `unique_id` parts) | | OWN (counted kill-switch legacy) | | |
| `camera_census.py:5395-5445` registry-empty legacy scan `endswith("_last_recognized_face_2")` | | OWN (fallback after registry) | | add counter |

### C4 Person identity strings
| file:line | infers | class | consumer | note |
|---|---|---|---|---|
| `person_coordinator.py:130-141` `tracked_person_entity_id` | person id from name | the ONE rule (becomes `person_ids.py`) | all | OWN |
| `person_coordinator.py:821, :993, :1743-1747` name -> `person.x` | person entity | COVERED (read-api RA4/RA9) | F1 | `_find_person_entity` tries 2 guesses then `None` |
| `person_coordinator.py:1782-1790` private_ble tracker by `first_name in entity_id or normalized in entity_id` | person -> tracker | MIGRATE: `person` entity attribute / `.storage/person` `device_trackers` (L4) -> tracker registry entry -> `device_id` -> sibling `sensor.*_area` | SEC-adjacent (location, census BLE leg) | the 2 live private_ble trackers cannot match by name |
| `person_coordinator.py:1795-1799` patterns `sensor.{first}_iphone_area`, `sensor.{name}_area` | person -> area sensor | MIGRATE (same device lookup) | location | OWN override `CONF_BERMUDA_AREA_SENSORS` exists and is the right config home |
| `person_coordinator.py:1803-1812` Bermuda area sensor by `first_name in entity_id` | | MIGRATE | location | substring: a first name that is a substring of another person's id collides |
| `person_coordinator.py:1838-1853` distance sensors `normalized_person in eid or person_no_sep in eid` | person -> distance sensors | MIGRATE: Bermuda device of the tracker (`device_id`) -> its `distance_to_*` entities | COMFORT (music following `closest_distance`, confidence) | **L3: Oji 0 of 114** |
| `person_coordinator.py:1885-1897, :1981-1985` scanner name vs entity-id substring both directions (`a in b or b in a`) | scanner <-> area scanner | MIGRATE: scanner device_id from Bermuda attributes / device registry area | | substring collision class ("den" in "garden" was fixed for rooms only) |
| `aggregation.py:6179-6186` `sensor.bermuda_{first}_` | person -> bermuda sensors | MIGRATE or DELETE (L2: matches 0 entities) | display | likely dead producer; verify consumer before delete (three-bucket) |
| `camera_census.py:3915` `_canonical_person_slug` first-token mapper, `:4010` guest head | face name -> person | COVERED (ship 1 makes it public); still a name guess. Registry/config alternative: per-person face-name alias in options; ambiguity already rule D-MED-2 | SEC (identity attach, notification naming) | keep, add alias config |
| `camera_census.py` Residuals A (`:3900-3912`), `:6159-6176`, `:6311-6320`, `perimeter_alert.py:5117-5121` | slug w/o space map | COVERED ship 1 (RA4) | | |
| `presence.py:5381, :7223`, `_ble_corroboration.py:40`, `arrival_edges.py:201,239`, `sensor.py:16420`, `switch.py:6572`, `binary_sensor.py:2125` | name -> slug for OWN unique_ids / own storage | OWN-ENTITY but must route through `person_ids.py` (RA9) | | unique_id built from slug; registry lookup by unique_id is correct form (`_ble_corroboration.py:49-55`) |
| display `.title()` copies (`notification_manager.py:4764-4766`, `transit_validator.py:2622`, `perimeter_alert.py:5549-5556`, `music_following.py:53-62`, `binary_sensor.py:121`, `__init__.py:3147`) | slug -> display | COVERED RA9; fix = read `person` friendly_name / `display_of` | NOTIF naming | notification_manager already reads friendly_name first |
| `music_following.py:609-611, :721` location vs room slug compare | room | OWN (URA location strings) | | covered by room-key decision, C5 |

### C5 Room slug -> own entity ids; area-name == room-name
| file:line | infers | class | consumer | note |
|---|---|---|---|---|
| `domain_coordinators/hvac_fans.py:1714-1729` `_read_room_occupied_state` -> `binary_sensor.{_slugify(room)}_occupied`, fail-open on missing | room occupied | MIGRATE: `ent_reg.async_get_entity_id("binary_sensor", DOMAIN, f"{entry_id}_occupied")`-style, same as `coordinator.py:3182-3198` / `fan_veto.py:384-398` | COMFORT (guard that SUPPRESSES fan OFF in occupied rooms, `hvac_fans.py:1886-1895`) | **L1: guard is silently off in 11 rooms.** Prior ledger: v5.51.0 M-1 fixed punctuation only |
| `hvac_fans.py:2031-2033` same for conflict observer | | MIGRATE | memory episode | |
| `memory_baseline.py:125-134` `_room_samples`: `binary_sensor/sensor.{room_slug}_occupied/_temperature/_humidity` | room signals | MIGRATE (entry_id + unique_id) | baseline learning (feeds NM conditioning) | 11 rooms learn no `occupied` baseline |
| `memory_facade.py:590-600` live read mirror of the above | | MIGRATE | | |
| `notification_manager.py:1803-1826` `sensor.{slug}_{signal}` of a hazard location string | location -> sensor | MIGRATE; `location` itself comes from safety (C7) | NOTIF | |
| `music_following.py:1114-1270` room -> media player: config first (OK), zone, `area.name` slug == room slug (:1166), `media_player.{room}` (:1220), volume scale by room slug (:1265) | room -> player / entry | MIGRATE: room entry has `area_id`; match `area_id` not name (L11: 11/47 names differ) | COMFORT | strategy 1 (explicit `room_media_player`) is the correct primary; rest are guesses; no counter |
| `person_coordinator.py:1561-1640, :2148-2261` room_name slug as location key and for `_direct_ble_rooms` | room key | OWN-ENTITY (URA location strings); Bermuda reports the area NAME so the name->area lookup is registry-backed and rename-fragile. Optional: key by entry_id | | `:1571` also adds `area.name` slug keys |
| `presence.py:6320-6327`, `presence_fan_recheck.py:1384`, `aggregation.py:6806`, `select.py:376`, `button.py:197,396`, `sensor.py:1881`, `coordinator.py:3197, :3872, :4631`, `switch.py:100`, `memory_writers.py:73`, `fan_veto.py:402-404,562`, `memory_facade.py:235-247, :759-894` | slug of room/zone name for compare, node ids, own object ids | OWN (names URA itself owns; node ids `room:<slug>` are keys, a room rename orphans them) | | `switch.py:100`, `coordinator.py:3197`, `fan_veto.py:404` are the registry-first-then-slug pattern: compliant if the fallback were counted |
| `config_flow.py:186` `guess_room_type_from_area` (keywords in area name) | room type | OWN/prefill: operator confirms in the flow | DISPLAY | allowed |

### C6 Lock regime
| file:line | infers | class | consumer | note |
|---|---|---|---|---|
| `domain_coordinators/security_lock_regime.py:1934-1950` `_person_for_sensor`: `sensor_id.endswith(f"_{obj}_distance")` | person from proximity sensor name | MIGRATE: proximity config entry `tracked_entities`/unique_id -> `person.*` (verify option key at plan time; I did not read the proximity integration source) | SEC (lockout approach, `:1978, :2457`) | L10 |
| `security_lock_regime.py:1925-1932` approach-zone compare `person_state.lower()` vs zone object id / friendly_name | zone | MIGRATE: compare `zone.*` state name from the registry/zone entity, `person` state IS the zone friendly name by HA contract; keep but state the contract | SEC | friendly_name equality is the HA behaviour; label as KEEP-DOCUMENT |

### C7 Entity kind / location / panel from name
| file:line | infers | class | consumer | note |
|---|---|---|---|---|
| `safety.py:1495-1514, :1548-1565` location: registry area first, then `_location_from_entity_id` strips suffixes and title-cases | hazard location | OWN-fallback; MIGRATE counter (silent today) | NOTIF (safety alert text) | |
| `safety.py:1541-1547` AQ kind by `"co2" in eid` after `device_class` | | OWN-fallback, add counter | SEC | |
| `presence.py:408-424` `_classify_entity_kind` substring fallback | motion vs mmwave | COMPLIANT: WARN-logged last resort ("Substrate-cycle"), not counted | presence trust | add counter; SENSOR_FLEET_CLASSES says classify by capability |
| `radar_tuning.py:140-158` `FIELD_ENTITY_SUFFIX` by `endswith` within one device | which number is which field | MIGRATE: `unique_id`/`translation_key`; device scoped so low risk | COMFORT (radar tuning writes!) | writes to numbers by name suffix |
| `energy_circuits.py:229` `"_2" in entity_id` -> panel left | panel | MIGRATE: device registry name / device_id (L9: 1 of 38 wrong) | DISPLAY/anomaly attribution | |
| `energy_circuits.py:450-457` `TRIPPED_BREAKER_CRITICAL_IDLE_S` substring in entity_id + friendly_name | critical-load class | MIGRATE: explicit config list of critical circuit unique_ids (name pattern here is the operator's data) | SEC-adjacent (tripped breaker detection) | |
| `energy_circuits.py:212` `startswith("sensor.span_panel_") and endswith("_power")` | span circuits | MIGRATE: `platform == span_panel` + `device_class` | | |
| `energy.py:10366-10373` `switch.<x>_grid_enabled` -> `binary_sensor.<x>_grid_status` | sibling | MIGRATE: same device_id | diagnostic | |
| `energy_outage_ledger.py:372-383` calendar by platform (registry) + suffix | | COMPLIANT (platform from registry); suffix only disambiguates, ok | | |
| `music_following.py:1084-1090` `"sonos"/"denon" in entity_id` | platform | registry strategy runs first (`:1060`); fallback uncounted | COMFORT | add counter |
| `appliance.py`, `hvac_override.py:883` | user -> person | `hvac_override.py:883` is registry/context based, OK | | |

### C8 UI prefill / display (allowed, listed for completeness)
`config_flow.py:1253,3708,4771,14841` (`mobile_app_` service names for dropdown), `automation.py:239`, `config_flow.py:1347` and `const.py:2037` name-token backstop after registry platform/category filters (`AUTODETECT_NAME_DENYLIST_PREFILL`), `house_status.py:121`, `perimeter_alert.py:5539-5556` friendly_name display, `energy_const.py` default entity ids (configuration defaults, not inference), hazard text `friendly_name`. DISPLAY or operator-confirmed.

## 6. CI guard: fail on a new name guess outside an allowlist

Goal: a test that is NOT a grep. Four parts.

1. **AST detector** (`quality/tests/test_registry_not_names_guard.py`). Parse every `.py` under `custom_components/universal_room_automation/` with `ast`.
   Flag nodes (prototype counts in §7 show these are tractable):
   - `endswith`/`startswith` call whose argument (constant or tuple of constants) starts with `_` (suffix vocabulary) or equals `_N` patterns;
   - `Compare(In)` with a left constant starting `_` (`"_person_detected" in eid`), and `in` of a lowercase-keyword on a name-like variable;
   - `JoinedStr` whose first literal is `<domain>.` and has a `FormattedValue` (built entity id);
   - `.lower().replace(" ","_")` chains, `slugify`, `_slugify` calls;
   - `re.sub(r"_\d+$", ...)` / `re.compile` with suffix patterns;
   - `split(".",1)[1]` subscripts feeding a further `endswith`/`replace`/`in` (object-id parsing) in the same function;
   - **vocabulary constants**: any module-level tuple/set/dict of >=2 strings all starting `_` (`_PERSON_SUFFIXES`, `EXTERIOR_*_SUFFIXES`, `FIELD_ENTITY_SUFFIX`) and every call site that passes a Name bound to one, so helper indirection (`_has_any_suffix(eid, _PERSON_SUFFIXES)`) is caught.
2. **Allowlist keyed by (file, enclosing function qualname, pattern id), with a COUNT**, not line numbers, in `quality/registry_not_names_allowlist.yaml`. Each entry: `reason` (own-entity | ui-prefill | counted-fallback | pairing-resolver | display | migrate-by:<card>), owner card, and `max_count`. A function exceeding its count fails (new guess added next to an old one). The test also fails on STALE entries (listed function no longer hits) so the list only ratchets down. `counted-fallback` entries must additionally reference a counter name that exists as a string in the same function (enforces "logged, counted last resort"). `migrate-by:` entries expire when their card ships (test reads board status).
3. **Anti-hollow controls** (feedback_hollow_test_anchors): (a) a fixture corpus of known-bad snippets (the 12 sites in §5 reproduced as strings) that the detector MUST flag, and known-good snippets (domain checks `eid.split(".")[0] == "light"`, URA own `f"{DOMAIN}_..."`) it must NOT; (b) a mutation test that inserts one new `endswith("_person_detected")` into a temp copy of an allowlisted function and expects the count rule to fail; (c) a self-check that the detector's raw hit total over the real tree is >= a floor (171 today with the prototype patterns) so a broken visitor cannot pass vacuously.
4. **Runtime complement**: one counter `name_fallback_total{site}` (per allowlisted `counted-fallback`), surfaced in a sensor attribute, with an NM trip-wire if non-zero over a day; and the live-fixture test `test_no_live_camera_entity_needs_name_fallback` already specified in the NVR plan generalised to person and room resolvers over a registry snapshot (the L1-L4 findings become fixtures: 47 rooms, 4 persons, 37 Frigate devices).

Detection limits to state in the test docstring: dynamic string building through `str.format`, `%`, or dict-of-lambdas is not seen; the allowlist test therefore also bans importing the suffix vocabulary constants outside `camera_resolver` / the pairing resolver.

## 7. AST prototype (baseline; throwaway, not committed)

Run 2026-11-13 over the same tree: `P3 f-string domain id 64` (camera_census 20, config_flow 10, person_coordinator 8, perimeter_alert 6), `P4 lower+replace slug 51` (person_coordinator 18, music_following 9, presence 4), `P1 endswith suffix literal 34` (camera_census 17, perimeter_alert 12), `P5 split(".",1)[1] 17` (camera_census 7, optimization 4, lock regime 2), `P2 "_x" in 5` (transit_validator 3). Many P3/P4 hits are OWN (switch/number/config_flow own ids) and become allowlist entries with reason `own-entity`; the expected allowlist at day one is ~60 entries, targeted to shrink as clusters migrate.

## 8. Migration plan per cluster (each Tier 2 unless noted; order by value)

1. **C5 room entity resolver** (Tier 2-DB: hvac_fans guard is regression-prone comfort; builder reads HVAC state of play). REUSE `coordinator._resolve_room_switch_entity_id` pattern (`coordinator.py:3182-3198`) and `fan_veto.py:384-398` as ONE helper `resolve_room_entity(hass, room_entry_id, unique_suffix)`; sites: hvac_fans x2, memory_baseline, memory_facade, notification_manager, music_following (use `area_id`). Fix is a behaviour change in 11 rooms: guard turns ON there; call out in README. Acceptance: with the live 47-room fixture, resolved id == registry id for all 47.
2. **C4 BLE person resolution** (Tier 2; presence state of play first): person -> `device_trackers` -> device_id -> area/distance entities; keep `CONF_BERMUDA_AREA_SENSORS` override first; delete `aggregation.py:6179` after consumer check. Acceptance discriminates: Oji distance-sensor count 0 -> 114 (L3), `closest_distance` populated.
3. **C1 gaps in NVR-WITNESS**: add `perimeter_alert.py:2179-2205` (snapshot cam name), `camera_census.py:3440-3445`, `:652` to the W2/W5b site tables; Reolink/Dahua `translation_key`.
4. **C2 pairing resolver**: decide the pairing form (operator table vs W1 evidence join); route every `_extract_camera_stem` caller through it; optimization.py:2653/3303 and `perimeter_alert.py:5318`.
5. **C6** proximity -> person via config entry.
6. **C3/C7** remainder; add counters to compliant fallbacks.
7. Guard test lands FIRST in warn mode (allowlist generated from this audit), then flips to fail after C5 and C1 ship.

## 9. Falsification and unknowns

- Would disprove L1: if the live `hass.states` carried an `entity_id` alias for the 11 rooms. Registry is the source of truth for ids; I did not read live states. Falsify at build time with `ha_get_state` for e.g. `binary_sensor.foyer_occupied`.
- L2/L3 read the registry only; Oji's `closest_distance`/confidence consumers (music following) not traced end to end. Consumer impact for C4 is therefore "probable", not proven.
- I did not verify the proximity config entry stores tracked person ids (C6), nor the Frigate `sensor_object_count` unique_id token across all 36 (one sample read).
- Fire check (producer fired?) not run for these resolvers; recommend the counter in §6.4 so it is measured in code. NVR leg fire counts are in the NVR plan §4.3 (garage_a 0/71 over 14 days, cited from the plan, not re-measured).
- Counts of sites per cluster are floors (helpers not followed beyond `camera_resolver`, `camera_census`, `perimeter_alert`).
