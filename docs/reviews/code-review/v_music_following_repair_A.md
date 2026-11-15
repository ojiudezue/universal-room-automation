# Review A: music following repair (local correctness + person-awareness layer conformance)

Branch `feature/music-following-repair`, diff base `develop` @ 0ac39b2a (three-dot, verified), builder commits
c5851233, be8a3d08, a29c6058, c6dac1e7. Reviewer framing A plus layer conformance (CONTRACT_person_awareness_layer.md
rev 2 @ badc328a, §2.4, §2.4a, §3 INV-LAYER-READ, §4, §7). Targeted tests: 199 passed (repair, legacy MF, MF
coordinator, v5100). No full suite, no mutation drills (framing C owns those).

Read: CLAUDE.md (F1-F5, consumer classes, Registry rule), the plan, the contract sections above,
`music_following.py` (gate, path, transfer, release, bonus, reversal, house-state, players), `transitions.py` and
`person_coordinator.py` diffs, `domain_coordinators/music_following.py` diff, `__init__.py` live-key diff.

## Verdict: FIX-REQUIRED

Must fix before ship: A-H1 (layer re-route; it also fixes a false-block bug), A-H2 (extend mode on the MA path stops
the source). A-M1 and A-M2 should go in the same fix-up (both small).

## Findings

### A-H1 HIGH: the BLE gate reads raw Bermuda entities and resolves them with its own resolver
`music_following.py:890-988` (`_ble_gate`, `_resolve_bermuda_sensors`, `_read_distance_ft`).
Classes: layer leak (INV-LAYER-READ: "a raw ... Bermuda person entity (including ids ... resolved from the
registry)"), #63 two meanings of "the person's BLE area", duplicate of BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1.

- Music is class `comfort` and must consume F4-BLE through `ura_person_location_change` (contract §7: "consumes F4-BLE
  through `ura_person_location_change`") or the §4.1 pull (`get_person_location(name)`, G6 `persons_in_room`).
  Instead it walks `person.*` -> `device_trackers` -> Bermuda tracker -> same-device sensors, and reads their
  states.
- Correctness consequence, not only form: the producer chooses the area sensor with `_find_bermuda_area_sensor`
  (`person_coordinator.py:1761-1820`: config override `CONF_BERMUDA_AREA_SENSORS`, then private_ble derivation,
  then name patterns). Music re-resolves through `person.device_trackers`. The gate then compares the event's
  `bermuda_area` (producer's sensor) with the live state of music's sensor (`:917`). When the two resolvers pick
  different entities, "normal" blocks every move. Legal repro: a person with a `CONF_BERMUDA_AREA_SENSORS`
  override to their watch's area sensor, while `person.<p>.device_trackers` lists the phone's Bermuda tracker;
  walk with music playing; the watch and phone areas differ at room edges and music records
  `ble_low_confidence area_moved` though the person did not move after the event. The reverse case (no Bermuda
  tracker on the person entity, `:967`) makes the gate fail open on every transition, so "normal" silently behaves
  as "any"; only `counters_today.ble_input_missing` shows it.
- The event already carries `area_sensor` (the producer's entity, `person_coordinator.py:1068`), so music has no
  reason to resolve anything.

Small re-route (fits before ship, about 30 lines plus test edits):
1. Area check: replace the live Bermuda read with the layer's live location for the person:
   `PersonTrackingCoordinator.get_person_location(person)` (`person_coordinator.py:2000`, §4.1 F4 row) compared with
   `transition.to_room`. "normal" blocks when the person's resolved room is no longer `to_room`. This also compares
   rooms, not raw Bermuda area names (Bermuda areas resolve to rooms through scanner areas, so an area-name compare
   is the wrong unit anyway).
2. Distance ("strict" only): have the producer add one additive key to the event it already fires
   (`closest_distance_ft`, measured where `_calculate_confidence` reads the distance sensors) and carry it on
   `RoomTransition` like `ble_area`. This is the plan's original D1 shape ("captured at fire time so MF never reads a
   mid-update `person_coord.data`"). If that does not fit, ship with "strict" falling back to the event-time area
   check and card the distance, rather than keep a raw read.
3. Delete `_resolve_bermuda_sensors` and `_read_distance_ft`. Registry resolution of the person's BLE sensors stays
   with BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1 in the producer.
4. Keep fail-open + `ble_input_missing` for: no location for the person, location `unknown`, event without BLE keys.

Also under the same contract row (MEDIUM, may be carded to G6 if the operator prefers): `_source_has_other_occupants`
(`:1674-1683`) and `_dwell_room_for_person` (`:1699-1703`) read `person_coord.data` directly. Contract §7 names
these for replacement with G6 `persons_in_room`. Until G6 exists they need an allowlist row (reason, owner card,
max count) per §6 item 3.

### A-H2 HIGH: "Play in both rooms" moves the music when the MA path is taken
`music_following.py:1103-1114` (`_resolve_path`) picks MA regardless of `rec.follow_mode`; `_start_target`
(`:1277-1285`) calls `music_assistant.transfer_queue`, which moves the queue and stops the source player. The
branch's own fake models exactly that (`test_music_following_repair.py:259-262`, source set `idle`). Under
`extend` nothing restarts the source, so an operator who chose "Play in both rooms" gets a move on every
MA-covered pair (the Sonos/master case the operator cares about). `test_mf_extend_mode_never_quiets_source`
(`:795`) only uses the WiiM pair with no MA twin, so the suite is green.
Repro: `mf_follow_mode=extend`, Kitchen -> Study A (both MA-covered in the rig), Kitchen playing; after the move
Kitchen reads `idle`.
Fix: under `extend`, skip `transfer_queue`; use a group join (MA entities support `media_player.join`, leader = MA
source) or the native/generic path. Add the parametrised MA case to the extend test.

### A-M1 MEDIUM: hazard stop no longer reaches speakers MF itself drives
`domain_coordinators/music_following.py:673-690` with `music_following.py:1764-1776`. Scope is
`room_media_player` + zone players only. MF also drives area-resolved primaries (`_get_room_player` `:1795-1824`
when a room has no `room_media_player`), MA twins (`target_eff`) and bonus players (`_bonus_joined`). Before this
branch a hazard stopped every playing player; now music MF moved into an area-resolved room keeps playing through a
safety stop. Class: one-missed-site (#53). Fix: union in the area-resolved primary of every room, `_active_groups`
leaders and members, `_bonus_joined` players, and the MA twins of each (`_ma_candidates`).

### A-M2 MEDIUM: name matching in the room player resolver (Registry rule)
`music_following.py:1800-1803` matches the HA area by `_slug(area.name) == _slug(room)`, and `:1827` guesses
`media_player.<room slug>`. Both are pre-existing (base `:1166`, `:1220`) but carried into the rewrite. The room
entry has `CONF_AREA_ID` (already used by `_bonus_candidates` `:1411`); resolve the area by id, and drop the
`media_player.<slug>` guess or keep it as a logged, counted last resort per the rule. Also `_room_cfg` (`:1757-1762`)
matches rooms by slugged name, which is URA's own config and allowed.

### A-L1 LOW: `ble_input_missing` can count twice for one transition
`:914-923`: "no_event_area" counts, then under "strict" "distance_dead" counts again. Count once per transition
(set a flag) so the counter means transitions, not reads. Moot if A-H1 is applied as described.

### A-L2 LOW: per-room opt-out checks only the target
`:841-843`. A room with `music_following_enabled=False` still has its music moved out when someone leaves it. Decide
and document which side the switch covers; the UI label should say so.

## Cleared (holds because)

| Check | Result |
|---|---|
| Area match under "normal", distance only under "strict" | Structure correct (`:920` gates distance on STRICT and `distance_ft>0`); the compared entities are wrong (A-H1) |
| Missing/dead input fails open with counter | Holds: unresolved, area dead, no event area, distance dead all return None and count `ble_input_missing` (`:903-923`) |
| MA `transfer_queue` call shape | `target={"entity_id": to_ma}`, data `source_player` + `auto_play`, blocking (`:1278-1282`); matches the plan and the fake's schema |
| Native join leader | `entity_id` = leader (MF group leader, else `group_members[0]`, else source), `group_members=[target]` (`:1126-1133`, `:1287-1290`); leader-release unsafe falls to generic in move mode (`:1127-1134`, safe-set empty) |
| Fade / stop / volume restore | Fade only after the call succeeds and not on MA (`:1221-1231`); verify failure restores at once (`:1251-1256`); release restores in `finally` (`:1342-1343`); every restore pops `_saved_volumes` (`:1170`) |
| Verify on the primary only | `:1237` reads `rec.target_player`; bonus joins only after booking success (`:1264-1265`) |
| Every outcome exactly once | `_finish` is idempotent on `rec.outcome` (`:596`); cancel-before-start booked by the done callback (`:727-734`); success booked before release so supersede of a releasing move does not re-book |
| Reload-suppressed keys | All 13 live MF keys in `_MF_LIVE_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py`), applied through one `apply_config`; ping-pong pushed to the detector (`:401-409`); `music_on_arrival_start` kept in the form and suppressed (operator ruling) |
| Teardown | in-flight tasks cancelled and awaited, reversal watches unsubscribed, episode writes flushed, diag listener unsubscribed by the coordinator |

## Layer conformance table

| Fact | Use | Current read | Conformant read | Status |
|---|---|---|---|---|
| F4-BLE (room change) | trigger | `TransitionDetector` listener fed by `ura_person_location_change` | same | PASS |
| F4-BLE (still there / distance) | gate | raw Bermuda sensors via own registry resolver | `get_person_location` + additive event key | FAIL (A-H1) |
| F4-BLE (others in source room) | gate | `person_coord.data` | G6 `persons_in_room` (or allowlist row until G6) | FAIL, allowlist acceptable |
| F1 bedroom/dwell | night gate | `person_coord.data` | G6 / profile | FAIL, allowlist acceptable |
| Class | | comfort | comfort | PASS |

## Summary

| Severity | Found | Must fix pre-ship |
|---|---|---|
| HIGH | 2 | 2 |
| MEDIUM | 2 (+1 allowlist item) | 2 recommended |
| LOW | 2 | optional |

Bug classes: layer read leak / #63 two meanings (A-H1), mode-ignored-by-one-path #53 (A-H2, A-M1), registry-not-names
(A-M2). QUALITY_CONTEXT candidate: "a mode knob honoured by N-1 of N paths" (A-H2) is a #53 variant worth a line.
