# v5.108.15 — The exterior seam file actually loads

Card: EXTERIOR-SEAM-FILE-LOADER-1. Plan: `docs/planning/PLANNING_exterior_seam_file_injection.md` (D4, D5, D6 and the
missing load wiring). Review: `docs/reviews/code-review/v_exterior_seam_loader_AB.md` (SHIP, three LOWs; two fixed,
one documented). Tier 2.

## What was wrong

The operator ratified `/config/universal_room_automation/exterior_seams.json` on 2026-09-14 as the primary source of
exterior camera seams, with `EXTERIOR_ADJACENCY_GRAPH` in `const.py` as fallback. The parser and validator were built,
but nothing in production imported them: the track linker ran on the constant only. The plan's status table said
"BUILT".

## What changed

- At linker setup, before the Frigate listener is registered, URA reads the seam file off the event loop and validates
  it against the configured perimeter and egress camera keys. Valid: its graph and its derived egress-adjacent cameras
  are installed. Missing: the built-in graph. Invalid or unreadable: the whole file is rejected, the previous graph
  stays (never an empty graph), one WARNING names the first error.
- `button.ura_reload_exterior_seams` (Security Coordinator device) re-reads and applies an edited file without a
  restart; a rejected reload keeps the last good graph.
- The "Outside: Open Tracks" diagnostic sensor shows `seam_source`, `seam_count`, `seam_validation`,
  `seam_file_sha256`, `seam_egress_adjacent`.
- Approach classification reads the installed egress-adjacent set, not the constant.

## Effect on the house

None today: the live file equals the constant (21 seams, 13 cameras, egress-adjacent armcrest, front_side_ptz,
g5_bullet, rear_ptz, utilities_ptz). Expected validator warning: `sonoffwindow` is a configured perimeter camera not in
the ring.

## Tests

`quality/tests/test_exterior_seam_loader.py` (14), including a wire-in test that drives the real setup path and a
registration anchor for the button. Mutation drills: removing the load call reds 12 tests; removing the button from the
setup list reds the registration test; eight more per-site drills by the builder. Full suite on 110cb2da: one
order-dependent failure in this file's id test (stubbed ButtonEntity in the full run), fixed by reading
`_attr_unique_id` (55284696).

## Validated 2026-11-12 (restart 21:55 CST, house home_night)

| Criterion | Result | Evidence |
|---|---|---|
| Installed | PASS | HA manifest v5.108.15; installed `exterior_track_linker.py` imports `exterior_seams` (checked on the HA config mount, the check the broken-promise sweep got wrong) |
| File is the live source | PASS | `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` `seam_source` "exterior_seams.json (schema 1, 21 seams)", `seam_count` 21 |
| Validation | PASS (expected warning) | `seam_validation` "ok (1 warning(s): configured exterior camera(s) absent from the ring: ['sonoffwindow'] ...)" |
| Egress-adjacent from file | PASS | `seam_egress_adjacent` armcrest, front_side_ptz, g5_bullet, rear_ptz, utilities_ptz (same as the constant) |
| Reload button exists | PASS | `button.ura_reload_exterior_seams` state unknown (never pressed) |
| No URA ERROR | PASS | system_log ERROR search universal_room_automation: 0 entries |

## Not done

- D3 upload UI (out of scope; the file is edited over Samba).
