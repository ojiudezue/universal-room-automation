# DRAFT README: scoped egress mute for perimeter alerts (PERIMETER-GLOBAL-EGRESS-MUTE-1)

Status: DRAFT, not deployed. Version is assigned at deploy. Plan:
`docs/planning/PLANNING_perimeter_egress_mute_scoped.md`. Tier 2-DB.
Identity model: consumes F3 (door crossing + identity attach). Security consumer class (>= 0.9).

## What changed

Before: any on-edge of any egress camera muted EVERY perimeter-only camera for 120 s, with no
identity check and no record. Over ~9 days that dropped 243 of 607 perimeter person edges (40%).

Now (operator decision A, "alert now, name it afterwards"; no hold anywhere):

- A perimeter-only edge on camera P is dropped ONLY when a door that lists P in
  `egress_mute_covers` has a crossing already stored, at most `EGRESS_MUTE_WINDOW_S` (120 s)
  before the edge, which is: direction `entry`/`exit`, a tracked resident (guests never),
  identity >= 0.9, not synthetic-corroborated. One unknown, below-floor, synthetic, guest or
  ambiguous crossing at any covering door in the window vetoes the mute. A camera's mute episode
  is capped at 300 s and ends after 120 s with no mute.
- Every mute, and every decline while a covering door was active, writes one
  `perimeter_gate_decision` row: `gate: "egress_mute"`, `suppressed: true|false`,
  `demoted: false`, `reason` in `egress_mute_known_resident | _vetoed_unknown | _no_record |
  _below_floor | _synthetic | _ambiguous | _cap | _realert`, inputs (door, person_id, confidence,
  direction, crossing_ts, seconds_since, episode_age_s).
- **Door groups (review D2).** When the integration option `door_groups` (`CONF_DOOR_GROUPS`) is set,
  every door in a group is one door for the mute: transit collapses one physical crossing per
  `group|direction` for 30 s and emits it under whichever leg camera resolves first, so a crossing
  emitted under `doorbell_lite` counts for the `garage_a` cover (qualify, veto, on-edge stamp,
  re-alert, zero-fire count), and one under `front_door_aerial` for the `madrone_g6_entry` cover. Read
  from the config option at setup, never from names. A camera with no group keeps its own door key;
  with `door_groups` unset the behaviour is byte-identical to per-door keying. Crossing records are
  still stored per door key (D10.5 reads them per camera); the group widening happens at read time.
  `egress_mute_covers` validation is unchanged: a cover key may be any configured egress camera.
- **Late re-alert (review A2, operator decision "(a) Re-alert late").** A crossing record lands
  ~45 s after its door edge, so a stranger's own crossing can arrive AFTER a covered camera's edge
  was already muted by a resident's crossing. When a crossing that does NOT qualify (unknown,
  guest, below floor, synthetic, ambiguous) lands at a door covering camera P, every edge on P
  that the mute dropped inside that crossing's window (0 <= edge - crossing <= 120 s, the same
  test that would have vetoed it) is sent then: one `egress_mute_realert` row (inputs: door,
  muted_by_door, veto_reason, the crossing, muted_at, late_by_s) per muted edge, and ONE run of
  the normal perimeter handler per camera with the mute step skipped (review D1: all of a camera's
  eligible edges are marked before that single task is scheduled, because the handler's in-flight
  guard is set only after awaits and would not fold same-tick siblings). Cooldown and every later
  gate apply as for a fresh edge, so several muted edges on one camera give one page, and a camera that
  already paged inside the cooldown records a `cooldown` suppression instead. Each muted edge is
  re-sent at most once. A qualifying crossing never re-sends. Muted-edge memory is RAM only and is
  cleared by restart/reload (a restart between the mute and the late record loses the re-send).
- Fail-open: missing linker / census / map, an unmapped camera, or any error = alert.
  Restart (or reload) clears the crossing memory and episodes.
- Dual-role cameras keep INV-EGRESS-SELF, with one fix (review A6): `EGRESS_MUTE_WINDOW_S = 0`
  now means never mute there too (before, a stamp at age exactly 0.0 still muted).
- **D10.5 changes in one way (review A4, stated honestly).** It skips the new unknown-crossing
  entries, so for crossings it saw before it is byte-identical. But crossings are now keyed by the
  configured door (D1), so a crossing whose `egress_camera` is a leg that used to key under its raw
  entity id (e.g. `sensor.garage_a_person_count`) now lands under the door key, where D10.5 can
  read it: D10.5 can see MORE identities than before. Unknown entries also share the 16-entry
  per-door cap. No dual-role camera is configured live (perimeter and egress lists do not overlap),
  so D10.5 has no live consumer today and there is no live effect.
- **Door-key map from the producer's own legs (review A3).** The entity -> door map is built from
  the egress producer's leg set (`census.get_transit_egress_entities_by_camera()`, the per-camera
  form of `get_transit_egress_entities()`, registry-resolved), plus the subscribed legs, base,
  count sensor and camera entity. A crossing from an entity still not in the map falls back to
  the name key; each such entity is logged once at INFO and counted on the diagnostic
  (`egress_mute_door_key_fallbacks`); producer legs missing from the map at wiring are listed in
  `egress_mute_unmapped_producer_legs`. Both should be empty live.
- Crossing records land ~45 s after the door edge (`EGRESS_ENTRY_WINDOW_SECONDS`), and only ~17%
  carry >= 0.9, so most resident walk-outs now ALERT and are named by the identity follow-up.
  That is the decided residual.
- Trip-wires (NM, MEDIUM, plus an `anomaly_log` row): mute ratio above 0.5 over 24 h with at
  least 10 rows (`perimeter.egress_mute_ratio`); and 5+ crossings in 24 h with zero egress_mute
  rows while a coverage map is loaded and the manager has been up 24 h
  (`perimeter.egress_mute_zero_fire`). Zero-fire counts only crossings at doors that are keys of
  `egress_mute_covers` (an uncovered door can never produce a mute row). Trip-wires never schedule
  after teardown, and their tasks are tracked and drained at unload.

## Operator step (required for any mute to happen)

The coverage map is config, not code. Until it is added, the mute never fires (every edge
alerts) and the diagnostic shows `mute_covers_source: absent (no egress mute)`.

1. Open `/config/universal_room_automation/exterior_seams.json`.
2. Add this top-level key (copy from `docs/examples/exterior_seams.example.json`):

   ```json
   "egress_mute_covers": {
     "garage_a": ["g5_bullet", "rear_ptz"],
     "madrone_g6_entry": ["sonoffwindow", "front_side_ptz", "utilities_ptz"],
     "front_door_aerial": ["sonoffwindow", "front_side_ptz", "utilities_ptz"]
   }
   ```
3. Press `button.ura_reload_exterior_seams` (or restart).
4. Check `sensor.ura_security_coordinator_outside_open_tracks_diagnostic`:
   `seam_validation` starts with `ok`, `mute_covers_source` = `loaded (3 door(s))`, and
   `seam_count` / `seam_egress_adjacent` are unchanged from before the edit.

Covered cameras must be perimeter-only cameras (review A5). `doorbell_lite` was in the plan's
`garage_a` list but it is an egress camera (configured in `egress_cameras`, not perimeter), so its
edges never take the scoped mute; the validator now rejects it and it is dropped from the map
above. Nothing that used to be muted by the plan's map is lost by this.

Any error in the section (unknown camera, door that is not a declared egress camera, a covered
camera that is not perimeter-only, empty list or empty name) rejects the WHOLE file. A rejected
file keeps the previous good adjacency GRAPH (ring, linking, burst-demote and circling are
unchanged), but switches the egress mute OFF (`mute_covers_source: rejected (no egress mute)`)
until a valid file is reloaded: an edit the validator refused must not leave an older, possibly
wider, map muting (review A1, INV-MUTE-FAILOPEN). One file, one verdict: a typo in the covers
also blocks a graph edit in the same file. Deleting the file also clears the map (`file absent`).
Delete the section to switch the mute off.

## Knobs (rung 1, module constants in const.py)

| Knob | Value | Kill / extreme |
|---|---|---|
| `EGRESS_MUTE_WINDOW_S` | 120 | 0 = never mute (also the dual-role window) |
| `EGRESS_MUTE_MIN_IDENTITY_CONF` | 0.9 | below 0.9 clamps to 0.9; above 1.0 = kill |
| `EGRESS_MUTE_MAX_EPISODE_S` | 300 | 0 = never mute |
| `EGRESS_MUTE_EPISODE_RESET_S` | 120 | quiet gap ending an episode |
| `EGRESS_MUTE_RATIO_ALARM` | 0.5 | above 1.0 disables; 0 = any mute alarms |
| `EGRESS_MUTE_RATIO_MIN_ROWS` | 10 | rows before the ratio may judge |
| `EGRESS_MUTE_ZERO_FIRE_MIN_CROSSINGS` | 5 | 0 disables the zero-fire trip-wire |
| `EGRESS_MUTE_TRIPWIRE_WINDOW_S` | 86400 | window and re-alarm cooldown |

## Live validation (prospective; replace with a `Validated <date>` table after restart)

- **Map loaded:** diagnostic `mute_covers_source` = `loaded (3 door(s))`; `seam_count` and
  `seam_egress_adjacent` identical to the pre-edit values.
- **Mute ratio drops from ~40%:** over the first day, perimeter person on-edges on covered cameras
  that were dropped / all perimeter person on-edges is far below 40% (recorder on-edges vs
  `perimeter_gate_decision` rows with `gate=egress_mute AND suppressed=1`).
- **Every mute has a row:** count of `_last_suppression` reason `egress_mute` events equals the
  `egress_mute` rows with `suppressed=true` (and no perimeter on-edge on a covered camera is
  missing from both `notification_log` and the gate rows).
- **No stranger muted without a qualifying crossing:** every `suppressed=true` row carries a
  `person_id` that is a tracked resident, `confidence >= 0.9`, `direction` entry/exit, and a
  matching `person_entry_exit_events` crossing on that door within 120 s before `at`.
- **Alert now:** a driveway edge during door activity with no qualifying crossing produces an
  `exterior_person` `notification_log` row and an `egress_mute` decline row (`no_record` or a veto
  reason); a later "that was <name>" follow-up names a known resident when one is matched.
- **Discriminator:** under "the window just got shorter", a no-record edge 1 s after a door
  on-edge would still be dropped; here it alerts with reason `egress_mute_no_record`.
- **Trip-wires quiet:** no `perimeter.egress_mute_ratio` / `perimeter.egress_mute_zero_fire`
  anomaly rows on day one (a ratio alarm means the mute is blanket again).
- **Door-key map complete:** diagnostic `egress_mute_unmapped_producer_legs` = `[]` and
  `egress_mute_door_key_fallbacks` = `{}` after a day of crossings.
- **Late re-alerts:** count `egress_mute_realert` rows; each should pair with an earlier
  `suppressed=true` row on the same camera and a non-qualifying `person_entry_exit_events` row on
  a covering door within 120 s before the muted edge.
- First-day row counts by reason: record from `egress_mute_counts_by_reason`.
- Note (review B): `perimeter_gate_decision` had 0 rows in the live DB at review time. Confirm gate
  rows persist live before relying on them for the checks above.
