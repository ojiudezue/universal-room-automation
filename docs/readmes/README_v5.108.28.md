# v5.108.28: interior vision ship 1 (room records, entry paths, no AI calls)

Cards: VISION-INTERIOR-SHIP1-1 (this release; child of VISION-INTERIOR-SIGHTINGS-1, which stays open for ship 2
on-demand descriptions, the vision count, the ledger floor and the D4 census flip).
Plan: `docs/planning/PLANNING_vision_interior_sightings.md` (approved 7b818ce1; ship-1 fix-up edits on this branch).
Branch `feature/interior-vision-d1` (build 9931a001, review C 23b0c0ff, fix-up 6025e9ba, merge-fix 525f0cb4, c4dd65ce).
Tier: D1 / D5 Tier 2-DB, reviewed as Tier 3 (A, B, C mutation, D + G).

**Display and record only.** No model call is made in this release. Nothing here changes AWAY, house state, the census
trust or comfort view, any actuator, presence, or any `person_id`. Operator 2026-11-15: interior counting is "for census
instead and the ledger", never presence. The census term (D4) and the ledger floor ship later, behind their own reviews.

## What ships

- **D1 room records.** For each room in a shared (not bedroom / bathroom) area with an interior camera group, the
  person-awareness producer builds one record every `INTERIOR_ROOM_RECORD_INTERVAL_S`: bodies seen by the NVRs, named
  residents (BLE-placed active residents plus faces), unnamed = bodies minus named, and a status (`missing` when no
  camera member is LIVE, `unnamed_present`, `confirmed`, `ble_unconfirmed`, `empty`).
  - Camera members that the census watchdog discounts as stuck are class `stuck`, never live, and never reach a record.
  - Groups rebuild when a room entry, its area, its type, the path map or the camera resolver changes (no restart).
  - New sensor `sensor.ura_interior_awareness` on the Whole House device: state = unnamed people in covered rooms with a
    LIVE member; per-room attributes, all unrecorded. Unknown when no room has a live reading.
- **D5 entry path, no-model leg.** After an entry crossing on a mapped door, the producer follows the person-sensor
  on-edges room by room along the door's path map (cumulative window) and writes one `interior_path` memory row with the
  hops. Nodes outside the interior groups that have a person sensor are listened to as well (the garage_a chain).
  `n` comes from crossing vision's count when it exists, else the arrival record, else the first hop's window maximum.
- **D7 trip-wires.** `interior_records_zero` and `interior_path_zero` (a path discharges only with at least one hop;
  hop-less paths are counted as `paths_zero_hop`). Unresolved door keys count toward the path wire.
- **Switch** `switch.ura_interior_vision` (default from the Camera Census Advanced field "Interior vision switch
  default"). Its helper says what is true today: room records only, no AI calls yet. Saving another Camera Census field
  never writes this one, and the parent entry does not reload.
- **Guard.** R15 pins `interior_tick`, `_emit_unnamed` and `area_evidence` to `PersonSightingProducer.*`.

## Validated 2026-11-15 (installed with v5.108.29, one restart ~21:47 CST, house home_night)

| Criterion | Result | Evidence |
|---|---|---|
| Installed and booted | PASS | manifest v5.108.29 (contains .28), `interior_vision.py` on disk; installed_version v5.108.29 |
| D1 room records | PASS | `sensor.ura_interior_awareness` populated ~2 min after restart (first record 21:48:50); 7 covered rooms: Master Hallway, Game Room, Garage Hallway, Living Room, Staircase, Upstairs Hallway, Foyer; all `liveness: live`, `provenance: nvr`; Living Room `unnamed_present` (bodies 1, unnamed 1), others `empty` |
| Not covered yet | finding | Playroom and Family Room cameras are in `camera_person_entities` but have no record (excluded type, twin merge or shared room; not yet resolved per camera) |
| Census unchanged | PASS by construction + suite | records have no reader in census/presence (R15 guard pins); golden `interior_records_on` equals develop |
| D5 path rows | pending organic | `last_path` None; no mapped-door entry since boot |
| No AI calls | PASS | the code path has no model call in this release; no `interior_vision` / `interior_description` rows |
| Logs | PASS | system log ERROR filtered on `universal_room_automation`: 0 entries |

Boot note: the sensor reads unknown for the first ~2 minutes after a restart, until the first record build and the next poll.

## Tests

Full suite on the merged branch (7d9517ba + 525f0cb4 + c4dd65ce): 22,920 passed before the last registry line, then
the form files 434 passed. New files: `test_interior_vision_records.py`, `test_interior_vision_surfaces.py`,
`test_interior_vision_fixup.py` (66). Review C: all 39 non-equivalent GREEN rows turned RED. Orchestrator mutation:
neutering the stuck-member rule (`stuck=False`) turns `test_census_discounted_member_never_reaches_a_record` red.

## Not in this release

Ship 2 (on-demand room descriptions), the vision count leg and ship 4 vision on the path, the D4 census flip, the
ledger floor, B LOW-2 (path-row tasks are cancelled, not drained, at teardown), A L8 (stale-reading age guard).
All tracked on VISION-INTERIOR-SIGHTINGS-1.
