# DRAFT — Transit "impossible move" only where a camera covers the move (ANOMALY-FLOOD-ROWS-1, option A)

Version not assigned. Rename to `README_v<version>.md` at deploy.

## What changed

The transit validator called a room move "implausible" whenever no hallway-type (shared-space) camera saw it AND
any shared-space camera anywhere in the house had fired in the last 10 minutes. It never asked whether a camera
could have seen that move. So walking from a bedroom into its own bathroom was "implausible" whenever someone was
in the hallway. Each one cut the move's confidence by 0.15 (enough to drop a normal move below music following's
0.6 bar) and wrote a `transit.path_implausible` anomaly row: 226-275 rows/day on 11-14..11-16, the top anomaly
metric.

Now the penalty applies only when the move's from-room or to-room itself holds a shared-space camera. Otherwise
the result is `no_camera_data`: no penalty, no anomaly row. Rooms map to HA areas through each room's configured
area (`CONF_AREA_ID`, the same helper the census uses); cameras map through the entity registry area, else the
camera device's area. No names are compared.

A confirmed sighting (+0.10), the concurrent-movers correlation and the penalty value are unchanged.

New diagnostics on the presence diagnostic sensor (via `TransitValidator.build_diagnostic_attrs`):
`path_coverage_not_covered_count` (moves spared the penalty) and `path_coverage_room_unresolved_count` (room
strings with no configured area, e.g. `away`).

Side fix: three unsub fields (`_rebuild_timer_unsub`, `_config_signal_unsub`, `_face_recog_signal_unsub`) were
initialised after a `return` and never ran; they are now set in `__init__` (all readers were already guarded).

## Files

- `custom_components/universal_room_automation/transit_validator.py`
- `custom_components/universal_room_automation/sensor.py` (presence diagnostic sensor carries the two counters)
- `custom_components/universal_room_automation/camera_census.py` (module-level `build_room_to_area_id_map`;
  the census method delegates, behaviour identical)
- `quality/tests/test_transit_path_coverage.py` (new), `quality/tests/test_phone_left_behind_camera_leg.py`
  (golden case 3 pins coverage True)
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`

## Live acceptance criteria (prospective)

- **DB:** `anomaly_log` rows with `type = 'transit.path_implausible'` drop from ~230/day to near zero for room pairs
  where neither room holds a shared-space camera (e.g. Master Bedroom <-> Master Bathroom, Jaya Bedroom <-> Jaya
  Bathroom, Kitchen <-> Breakfast Nook). Query the first full day after restart, grouped by from/to room.
- **DB:** `path_implausible` rows are still possible, and only for pairs where one side is a camera room (hallway,
  foyer, stairs, landing). Every surviving row's from or to room maps to an area holding a shared-space camera.
- **Sensor:** the presence diagnostic sensor shows `path_coverage_not_covered_count` rising through the day
  (roughly the old flood rate) and `path_coverage_room_unresolved_count` small (only sentinel locations).
- **Discriminator:** if surviving rows still include bedroom <-> own-bathroom pairs, the room or camera area
  mapping is wrong (check that room's `area_id` and the camera's registry area), not the rule.
