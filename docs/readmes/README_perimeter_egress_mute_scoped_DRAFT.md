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
  _below_floor | _synthetic | _ambiguous | _cap`, inputs (door, person_id, confidence, direction,
  crossing_ts, seconds_since, episode_age_s).
- Fail-open: missing linker / census / map, an unmapped camera, or any error = alert.
  Restart (or reload) clears the crossing memory and episodes.
- Dual-role cameras keep INV-EGRESS-SELF unchanged. D10.5 is unchanged (it skips the new
  unknown-crossing entries).
- Crossing records land ~45 s after the door edge (`EGRESS_ENTRY_WINDOW_SECONDS`), and only ~17%
  carry >= 0.9, so most resident walk-outs now ALERT and are named by the identity follow-up.
  That is the decided residual.
- Trip-wires (NM, MEDIUM, plus an `anomaly_log` row): mute ratio above 0.5 over 24 h with at
  least 10 rows (`perimeter.egress_mute_ratio`); and 5+ crossings in 24 h with zero egress_mute
  rows while a coverage map is loaded and the manager has been up 24 h
  (`perimeter.egress_mute_zero_fire`).

## Operator step (required for any mute to happen)

The coverage map is config, not code. Until it is added, the mute never fires (every edge
alerts) and the diagnostic shows `mute_covers_source: absent (no egress mute)`.

1. Open `/config/universal_room_automation/exterior_seams.json`.
2. Add this top-level key (copy from `docs/examples/exterior_seams.example.json`):

   ```json
   "egress_mute_covers": {
     "garage_a": ["g5_bullet", "doorbell_lite", "rear_ptz"],
     "madrone_g6_entry": ["sonoffwindow", "front_side_ptz", "utilities_ptz"],
     "front_door_aerial": ["sonoffwindow", "front_side_ptz", "utilities_ptz"]
   }
   ```
3. Press `button.ura_reload_exterior_seams` (or restart).
4. Check `sensor.ura_security_coordinator_outside_open_tracks_diagnostic`:
   `seam_validation` starts with `ok`, `mute_covers_source` = `loaded (3 door(s))`, and
   `seam_count` / `seam_egress_adjacent` are unchanged from before the edit.

Any error in the section (unknown camera, door that is not a declared egress camera, empty list)
rejects the WHOLE file and keeps the previous good spec. Delete the section to switch the mute off.

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
- First-day row counts by reason: record from `egress_mute_counts_by_reason`.
