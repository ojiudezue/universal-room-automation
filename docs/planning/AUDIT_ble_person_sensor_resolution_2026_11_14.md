# AUDIT: person BLE sensor resolution (card BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1)

Read-only probe, 2026-11-14 00:0x CDT (`date` = Sat Nov 14 00:09 CST). Develop at 67840210. Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (1080 lines) and memory `feedback_ble_config_is_tuned_check_before_asserting.md`. Not read in full: `docs/planning/AUDIT_registry_not_names_sweep_2026_11_13.md` (only its BLE rows L2-L4, C4, :104-108, :178).

## 0. Answer

1. The name-match defect is real, but it is the SMALLER of two defects. The per-person confidence producer has been dead for ALL four people since 2026-10-20: every per-scanner `*_distance_to_*` sensor in HA is `unavailable` with `restored: true` (356 of 356 states). Ezinne, Ziri and Jaya match by name and sit at a fixed 0.3 (the "no sensor produced a value" branch). Oji matches nothing and sits at the fixed 0.5 (the "no sensors found" branch). Registry resolution alone would take Oji from 0.5 to 0.3 and change no decision.
2. `closest_distance` is never available to anyone, for a second, independent reason (section 3.3). The only consumer, the music-following BLE distance gate, therefore fails open for everyone today.
3. Nothing in URA decides on the person BLE confidence value. All readers are display, DB columns, or a `< 0.3` filter that both 0.3 and 0.5 pass (section 3.1).
4. Existing line numbers in the card are stale. Current develop: `_find_bermuda_area_sensor` `person_coordinator.py:1753-1816`, `_calculate_confidence` `:1818-1928` (distance-sensor match `:1838-1853`; 0.5 "no sensors" return `:1855-1858`; the `closest_distance` write `:1922-1923`), call site `:1032-1042`, `aggregation.py:_find_bermuda_sensors` `:6170-6196`.

## 1. Registry path, person -> tracker -> device -> sensors

Sources: `/Users/okosisi/ha-config/.storage/person`, `core.entity_registry`, `core.device_registry`, `core.config_entries` (read-only mount); live `person.*` attribute `device_trackers` (identical lists, GET /api/states). Config: `tracked_persons` live = `['person.ezinne','person.oji_udezue','person.jaya','person.ziri']`; `__init__.py:3145-3153` converts each to a title-case display name (`person.oji_udezue` -> `Oji Udezue`), which is `person_name` in the coordinator.

| Person | device_trackers (platform) | Bermuda tracker, device | Bermuda sensors on that device (registry platform `bermuda`) |
|---|---|---|---|
| Oji Udezue | `phalanxiphone15promaxcflare` (mobile_app), `iphone_oji_bermuda_tracker` (bermuda), `private_ble_device_8ce182` (private_ble_device), `okosisipadmini6_2` (mobile_app) | device `IPhone_Oji` (id 435615c6...) | `sensor.iphone_oji_area`, `_distance`, `_nearest_scanner`, `_nearest_rssi`, `_floor`; 114 `distance_to_*` + `unfiltered_distance_to_*` (57 + 57), only 13 enabled |
| Ezinne | `ezinne_iphone` (private_ble_device), `ezinne_iphone_bermuda_tracker` (bermuda), `zinny_s_iphone_15` (mobile_app) | `iPhone_Ezinne` (97398998...) | `sensor.ezinne_iphone_area`, `_distance`, `_nearest_scanner`; 114 distance_to, 114 enabled |
| Ziri | `ziri_iphone` (private_ble_device), `iphone_ziri_bermuda_tracker` (bermuda) | `iPhone_Ziri` (ff7cce21...) | `sensor.iphone_ziri_area`, `_distance`; 114, 114 enabled |
| Jaya | `private_ble_device_249050` (private_ble_device), `iphone_jaya_bermuda_tracker` (bermuda) | `iPhone_Jaya` (89b8e4c4...) | `sensor.iphone_jaya_area`, `_distance`; 114, 114 enabled |

Registry linkage (verified in the files, not inferred from names):
- The Bermuda tracker entity (`platform: bermuda`) has `unique_id` = the Bermuda device unique_id (Oji `8ce182a9fd03...`). Its sensors derive from it: area `= <uid>`, nearest distance `= <uid>_range`, nearest scanner `= <uid>_scanner`, per-scanner `= <uid>_<scanner mac>_range` (registry values: `sensor.iphone_oji_area` uid `8ce182a9...`, `sensor.iphone_oji_distance` uid `8ce182a9..._range`; Bermuda `sensor.py:364-366, :405-409`).
- The private_ble tracker is a different device (Oji `f8ff410c...`, 5 private_ble entities, none Bermuda). Its entity unique_id is `<same id>_device_tracker`, and the Bermuda device carries identifier `['private_ble_device', '<same id>']` (Oji's `IPhone_Oji` device). Two registry routes to the same Bermuda device: (a) the person's tracker with entity platform `bermuda`; (b) the person's `private_ble_device` tracker via config-entry unique_id / device identifier.
- Every one of the four persons has a `bermuda`-platform tracker in `device_trackers`, so route (a) resolves all four today.

Resolves today by name vs by registry:

| Person | Area sensor today (`:1753-1816`) | Distance sensors today (`:1838-1853`) | By registry |
|---|---|---|---|
| Oji | `sensor.iphone_oji_area` via Strategy 4, `first_name in entity_id` (works) | 0 of 456 Bermuda distance entities match `oji_udezue`/`ojiudezue` -> `return 0.5` | resolves (13 enabled of 114) |
| Ezinne | `sensor.ezinne_iphone_area` via Strategy 2 (tracker id contains `ezinne`) | 126 match = 114 own + 12 from OTHER people's phones | resolves (114 own) |
| Ziri | Strategy 2 derives `sensor.ziri_iphone_area` (absent), falls to Strategy 4 `sensor.iphone_ziri_area` | 126 = 114 + 12 foreign | resolves |
| Jaya | Strategy 4 `sensor.iphone_jaya_area` (her tracker id has no `jaya`) | 126 = 114 + 12 foreign | resolves |

Room location therefore works for all four today; the defect is confined to confidence/distance.

Cross-person contamination (new finding, registry-verified): the substring test matches a scanner's name as well as the phone's. Examples: `sensor.iphone_oji_distance_to_jaya_3` (Oji's phone to the Jaya bedroom scanner) matches person "Jaya"; `sensor.iphone_oji_distance_to_switch_shelly1pmgen3_wifi_ezinnemakeup` matches "Ezinne". Each of Ezinne/Ziri/Jaya matches 12 foreign sensors (4 each from three other phones), 9.5% of their list. Those foreign sensors are exactly the 13 of Oji's 114 that are enabled today: the auto-enable block at `:1849-1853` for the other three people enabled them; Oji's own 101 stay disabled.

## 2. Producer check: is the value actually produced?

Arithmetic (`:1818-1926`): confidence = 0.5 if no matching distance sensor or no area scanner; otherwise 0.9 (one scanner < 5 ft, or two < 8 ft), 0.7 (one close), 0.5 (detected, not close), 0.3 (no sensor had a numeric state).

Dependency health (measured):
- Live states 2026-11-14: all 356 `sensor.*_distance_to_*` are `unavailable` with attribute `restored: True` (a registry entity no running integration owns). `ezinne_iphone`: 12 of 12, `iphone_jaya`: 47 of 47, `iphone_ziri`: 47 of 47, `iphone_oji`: 7 of 7.
- Recorder (7 d, `home-assistant_v2.db`, `ssh ha sqlite3 -readonly`): 0 numeric rows for any iPhone `distance_to_` sensor 2026-11-06 -> 11-14 (only `unavailable` rows).
- Long-term statistics: last numeric hour for the per-scanner sensors is 2026-10-20 07:00 UTC (02:00 CDT); only `bluetooth_adapter` ran to 2026-11-02.
- Meanwhile the nearest-scanner sensors are live: `sensor.ezinne_iphone_distance` = 1.31 ft at 2026-11-14 (unit `ft`, HA converts Bermuda's metres), `sensor.iphone_jaya_distance` = 3.94 ft, `_area` / `_nearest_scanner` populated.
- Cause of the 10-20 stop: UNKNOWN. Bermuda 0.8.7 (`manifest.json` dated Jul 11; config entry modified 2026-10-26, after the stop). Bermuda only creates a per-scanner entity when its scanner roster allows (`sensor.py:96-126`). Not investigated further (read-only; log window gap, see `reference_ha_logs_journald`; `ssh ha journalctl` does not exist).

Fire check (URA DB `person_presence_snapshots`, 15-minute cadence, and `person_visits`, 7 d):

| Person | snapshots method=bermuda, by confidence (7 d) | person_visits (7 d) |
|---|---|---|
| Oji Udezue | 71 of 71 = 0.5 (last row 2026-11-08 16:41 UTC; away since) | 351 of 351 = 0.5 |
| Ezinne | 497 of 497 = 0.3 | 1264 of 1264 = 0.3 |
| Jaya | 331 of 331 = 0.3 | 1209 of 1209 = 0.3 |
| Ziri | 53 of 53 = 0.3 | 334 of 334 = 0.3 |

So Oji is at exactly 0.5 on 100% of his BLE rows; the others are at exactly 0.3 on 100%. Dating: Ezinne's snapshot confidence was 0.9/0.7/0.5 through 2026-10-19 (e.g. 10-19: 85 x 0.9, 2 x 0.5), 20 x 0.3 + 8 x 0.9 on 10-20, then only 0.3 from 10-22 onward. Oji was 0.5 on every day in the series. The "Oji gets 0.5 and others get real values" premise in the card was true until 10-20 and is false now.

## 3. Consumer and forward trace

### 3.1 Person BLE confidence (`data[<name>]["confidence"]`)

| Consumer | file:line | Use | Effect of 0.5 vs 0.3 vs real value |
|---|---|---|---|
| `get_room_occupants` / `get_persons_in_room` / `get_persons_in_zone` | `person_coordinator.py:2154-2163` (threshold `< 0.3`, strict) | TRUST: room BLE occupants feed room fusion `ble_persons` (`coordinator.py:4313`, `:4876`), fan veto `fan_veto.py:308`, fan recheck L1, zone BLE (`presence.py:2422`) | None. 0.5 and 0.3 both pass `< 0.3`. A real 0.3 passes too (min of the ladder). Decay `max(0.1, c*0.5)` (`:1181`) drops either below 0.3 in one step. |
| Presence / HVAC / lock regime / census / transit | `presence.py:6059-6070, :7407`; `camera_census.py:2729, :3120`; `arrival_edges.py`; `security_lock_regime.py:1855-1892`; `perimeter_alert.py:5289` | read `location`, `method`, `tracking_status`, `previous_location` only | None. None reads `confidence` (grep of every `"confidence"` read in those files: no person-confidence use). Row-14 `0.82` and `0.9`/`0.75` stamp values (`:761`, `:796`, `:1276`) are on the non-Bermuda branch and are labels (state of play section 10 #24). |
| Display | `aggregation.py:2244, :5655-5665, :6032, :6252, :6411`; `sensor.py:3028-3040, :3284, :3338`; `person_coordinator.py:2324` | attribute `confidence` + `confidence_level` (high >= 0.8, medium >= 0.5, else low) | Oji shows "medium" (0.5), the others "low" (0.3). Display only. |
| DB | `person_coordinator.py:1075, :1421` -> `log_person_entry`, `log_person_snapshot` (`database.py:4069, :4122`) | columns written; readers `database.py:4142-4305`, `sensor.py:3145, :3221` select but do not filter on it | None found. |
| `room_transitions.confidence` (Bayesian priors, music) | `transitions.py:361-385` | computed from transit duration/path type, NOT from person BLE confidence | None. Music `MIN_CONFIDENCE` 0.6 (`music_following.py:521`; live `mf_min_confidence` 0.6) reads this transition value, so Oji's 0.5 does not block his music following. (The card's premise "music following gates on BLE confidence" is wrong for the confidence gate; see 3.3 for the distance gate.) |

### 3.2 Area (`location`, `bermuda_area`)
Produced by the area sensor, resolved by name today and working for all four (section 1). The registry change does not alter it unless the area-sensor lookup is also migrated (recommended, same helper).

### 3.3 `closest_distance`
- Producer: written only at `person_coordinator.py:1922-1923` into `self.data[person_name]`. That is the PREVIOUS tick's dict (`old_data` is read from `self.data` at `:983`); the new per-person dict is built after at `:1097-1112` with no `closest_distance` key and returned at `:1430`, then assigned by HA (`update_coordinator.py:416`, `self.data = await self._async_update_data()`). Nothing copies the key forward (grep: `closest_distance` appears only at `:1923`, `music_following.py:539-540`). So the value is lost every tick; a reader sees it only if it runs inside the tick before the assignment. The tick's awaits (`_find_bermuda_area_sensor`, `_calculate_confidence`, `_get_area_scanners`) contain no suspending awaits in the code read, so an event listener runs after the replacement. This is a code-reading conclusion, not a runtime observation (no way to read coordinator memory, and the HA log window is ~2 min).
- Independent second reason: it is only computed from a numeric per-scanner sensor inside the area (`:1893-1900`), and none exists (section 2).
- Only consumer: `music_following.py:533-548`, gate `closest_distance is not None and closest_distance > mf_dist` (live `mf_high_confidence_distance` 8.0 ft in the Coordinator Manager entry; set via `domain_coordinators/music_following.py:146`). `None` -> falls through (fail open). Fire count: UNKNOWN from logs; in code it cannot fire for any person.
- Who decides what: `MusicFollowing._handle_transition` (`music_following.py:480-560`): enabled-person check, transition confidence >= 0.6, then the distance gate, then the transfer.

### 3.4 What changes for Oji if the name fix alone ships
Confidence 0.5 -> 0.3, display "medium" -> "low", DB rows 0.3. No consumer changes behaviour. Nothing starts firing. Oji is `not_home` (NZ travel, person.oji_udezue `not_home` since 2026-11-14 00:51 UTC, `sensor.iphone_oji_area` = unknown); his 13 enabled distance sensors are `unavailable`.

### 3.5 What changes if the producer is also repaired (distance gate becomes live)
If `closest_distance` were stored correctly and fed from the live nearest-distance sensor, the 8 ft music gate starts blocking transfers it never blocked. Upper-bound estimate (`room_transitions` joined to `sensor.<dev>_distance` row at-or-before the transition within 120 s, 8 days to 2026-11-14, transitions with transition confidence >= 0.6 that also read > 8 ft):

| Person | transitions | conf >= 0.6 | of those with distance > 8 ft |
|---|---|---|---|
| Oji | 793 | 519 | 142 (27%) |
| Ezinne | 1321 | 778 | 295 (38%) |
| Jaya | 1272 | 828 | 155 (19%) |
| Ziri | 566 | 371 | 40 (11%) |

Caveat: these are all room transitions, not only music-enabled rooms or actual transfers; `sensor.<dev>_distance` is Bermuda's nearest-area distance, a slightly different quantity from "closest scanner in the resolved room". It is an upper bound for how much a working gate would change music following.

## 4. Recommendation

1. Resolve by registry, in one shared helper, e.g. `person_coordinator._bermuda_device_for_person(person_entity_id) -> device_id | None`: take the `person.*` state attribute `device_trackers` (same read already at `person_coordinator.py:303, :439, :714`), find the tracker whose entity registry `platform == "bermuda"` and use its `device_id`; fall back to route (b) (private_ble tracker unique_id minus `_device_tracker`, matched against the Bermuda device identifier). Reuse `er.async_entries_for_device` and the existing `_resolve_bermuda_entity_id` registry-by-unique_id pattern (`person_coordinator.py:473-480`, unique-id constants `const.py:281, :298`). Keep `CONF_BERMUDA_AREA_SENSORS` (`const.py:4138`) as the first override, as the sweep audit L4/:178 states. Person key: `person_ids.py` (`tracked_person_entity_id`), not another title-case round trip. A name test stays only as a logged, counted last resort (CLAUDE.md "Registry, never name guessing").
2. Use the same helper for the area sensor (retire Strategies 2-4 `:1790-1812`) and for `aggregation.py:_find_bermuda_sensors` (`:6170-6196`, matches `sensor.bermuda_<first>_*`: 0 entities, a dead producer; DELETE or MIGRATE after the consumer check: its only job is the PersonLocationSensor listener list, with a polling fallback when empty, `:6126-6148`).
3. Scope it as TWO cards, not one:
   - This card: registry resolution of the person's Bermuda device (confidence/area/aggregation). Honest acceptance: Oji's confidence value moves 0.5 -> whatever the producer then yields (currently 0.3), foreign-sensor matches go 12 -> 0 for the other three, no decision changes. The discriminator is the 0 foreign sensors and the count of resolved own-device sensors per person, NOT "Oji now gets a real confidence".
   - A new card (producer): the per-scanner `distance_to_*` sensors are restored ghosts since ~2026-10-20; cause unknown. Decide between repairing Bermuda's per-scanner entities (upstream/config, find the cause first) and re-basing `confidence`/`closest_distance` on the live `sensor.<dev>_distance` + `_nearest_scanner` + `_area` (also fixes the stale-dict `closest_distance` store). The second is a behaviour decision, because it turns on the 8 ft music gate (section 3.5). Probe before that card: a per-transition replay of the music gate on the chosen distance source.
4. The `closest_distance` store bug (write into a replaced dict) must be fixed in whichever card re-bases the producer, with a test that reads the value from `coordinator.data` after a refresh.

## 5. Risks of the registry change (list)

- R1, Bermuda reload: `_calculate_confidence` auto-enables every matched disabled distance sensor (`:1849-1853`). For Oji that is up to 101 disabled sensors. HA schedules a config-entry reload 30 s after an entity-registry `disabled_by` change to enabled (`config_entries.py` `RELOAD_AFTER_UPDATE_DELAY = 30`, `_async_handle_reload`, read in the local venv HA 2026.2.3; the live HA version was not checked), which would reload the Bermuda entry for the whole house: a BLE blink for every tracker. Do NOT carry the auto-enable into the registry version; remove it (the other three persons are already fully enabled, which shows it ran for them) or gate it behind an explicit operator action.
- R2, enabling 101 more entities, even if the integration does not reload, adds registry/recorder rows for sensors that are currently ghosts; moot once the producer is re-based onto the nearest-distance sensor.
- R3, behaviour change hidden in the producer fix: re-basing distance turns the 8 ft music gate on (section 3.5: 11-38% of confident transitions read > 8 ft). Needs operator decision and its own acceptance.
- R4, the 0.3 vs 0.5 shift for Oji is display-only today, but any future reader keying on `confidence >= 0.5` (the dashboards' "medium" threshold) would change; none found in code.
- R5, device trackers list order and multiplicity: Oji lists 4 trackers (two `mobile_app`, one private_ble, one bermuda). Pick the `bermuda`-platform tracker explicitly (do not take first or last in the list, state of play section 3 "last tracker of a source type wins" applies to the axes, not to this lookup); zero or two bermuda trackers = unresolved, fall back and count.
- R6, person with no Bermuda tracker (Wall Kiosk person item has none): resolver returns None; behaviour must stay the fixed fallback and be counted, not guessed by name.
- R7, boot ordering: the registry is available at tick 1, but the Bermuda device may not have loaded its entities yet; the fallback must not stamp a permanent "unresolved" cache (resolve per tick or invalidate on `entity_registry_updated`, as `camera_stream_health` does).
- R8, tests: existing tests may use fake name-shaped entities; the sweep audit already warns that `SimpleNamespace` fixtures hide registry-shape defects (state of play section 1, LOCK-ENTRY-AREAS-WRONG-OBJECT-1). Use a real registry fixture with the Oji shape (4 trackers, device with identifier `private_ble_device`).

## 6. Falsifiers run or open

- "All per-scanner sensors are ghosts" would be disproved by one numeric `*_distance_to_*` state: none in 356 live states, none in 8 days of recorder rows.
- "No decision reads person confidence" would be disproved by any threshold on it outside `:2154`: grep of `get_person_confidence`, `.get("confidence")`, `["confidence"]` over `custom_components` found only the readers in section 3.1.
- "`closest_distance` is lost each tick": open for a runtime check (needs a live probe or test; code read only).
- Cause of the 10-20 stop: open (no log access; Bermuda version file predates it).

## 7. Files

- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/person_coordinator.py` (`:983, :1032-1112, :1753-1928, :2154, :1922`)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/aggregation.py` (`:6126-6196`)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/music_following.py` (`:480-560`), `domain_coordinators/music_following.py:146`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/transitions.py:361-385`
- `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_registry_not_names_sweep_2026_11_13.md` (rows L2-L4, C4)
