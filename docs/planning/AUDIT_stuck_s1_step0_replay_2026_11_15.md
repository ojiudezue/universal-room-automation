# AUDIT: S1 step-0 replay (stuck-sensor truth, P22 off-gap tolerance)

Run 2026-11-15 22:0x CDT. Read-only. Gate for S1 in `PLANNING_stuck_sensor_truth.md` (rev 2) section 3 S1.
GO rule: no new >= 4 h run overlaps a BLE-confirmed person in that room for > 30 min.

## Verdict: GO (with two caveats below)

S1 (tolerance 10 s) creates exactly ONE new >= 4 h run in 7 days, on one input of 28:
`binary_sensor.occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2` (Guest Bedroom 2, the 11-15 case).
No BLE-tracked person was in Guest Bedroom 2 at any time during that run. Every other input: zero new runs.

Caveat 1: BLE overlap is vacuous for the upguest case. No URA person location sensor reads "Guest Bedroom 2" in the whole
7 days (distinct values listed per person in the data; none is that room), because the occupant was an untracked guest.
So the check cannot prove the room was empty, only that no BLE-confirmed person was there. The 11-15 stuck call rests on
the operator's ground truth, not on this replay.
Caveat 2: replay approximates tick timing (see Method). The verdict is the same under both tick models.

## Method

- Inputs: `core.config_entries` (domain universal_room_automation, 50 entries), keys `motion_sensors`, `presence_sensors`
  (the mmwave list), `occupancy_sensors`, `sensor_capabilities` only. 72 listed inputs; family from entity registry ->
  device registry `model_id` / `model` via the branch's own `family_for_model`; capability via `derive_capability`;
  class via the branch's `is_p22_motion_class` (imported read-only from the worktree). 28 inputs are motion class:
  by registry model: ZG-204ZV (zigbee_zv), ZG-204Z and SNZB-03P (pir).
- History: HA recorder (`ssh ha`, read-only URI), 7 days to 2026-11-15 22:01 CDT, state + `last_changed`. BLE truth:
  `sensor.universal_room_automation_{oji_udezue,ezinne,ziri,jaya}_location` state history (attributes show
  `tracking_reason: bermuda`, `tracker_sources.ble`), compared to the room title.
- Rule: a Python port of `_p22_stamp_tick` (branch `coordinator.py:2441-2514`) for tolerance 0 (develop) and 10 s (S1),
  then exclusion = run age >= `STUCK_P22_HOURS` 4.0. Same tick set for both rules, so the diff is rule only.
- Tick models: (grid) a 30 s grid (`update_interval` 30-35 s, `coordinator.py:711`); (edge) the grid plus an event tick on
  every state change of the input, with the 2 s leading/trailing rate limiter of `_trigger_rate_limited_refresh`
  (`coordinator.py:1639-1665`). Edge is the closer model; it reproduces the 11-15 develop exclusion 12:51:40 vs the
  plan's 12:51:52.
- Approximations: poll jitter and phase, other sensors' edges adding ticks, `_substrate_edge_wants_refresh` suppression,
  restart/boot guards (`_post_restart_seen_on`, settle) and the 7-day window start (a run in progress at the start is
  truncated) are not modelled. "New" = tick excluded under S1 and not under develop.
- Scripts: `.claude/tmp/s1probe_*.py` (inputs, pull, sim2).

## Per-input result (28 motion-class inputs, 7 days)

Columns: develop episodes >= 4 h / S1 episodes >= 4 h / new episodes (S1-only excluded time) / max BLE overlap (min) /
longest run in hours dev -> S1 (edge model). Inputs omitted from the top table have 0/0/0/0 and a longest run under
0.4 h (patio left 0.15 -> 0.31).

| Room | Input (short) | Dev | S1 | New | BLE overlap | Longest run h dev->S1 |
|---|---|---|---|---|---|---|
| Guest Bedroom 2 | hobeian_upguestroom_presence_2 (ZV) | 1 | 1 | 2 pieces of 1 new run | 0 | 4.46 -> 7.16 |
| Guest Bedroom 1 | hobeian_downguestroom_presence_2 (ZV) | 2 | 2 | 2 (12 s, 0 s boundary) | 0 | 5.68 -> 5.69 |
| Patio | hobeian_patioright_presence (ZV) | 0 | 0 | 0 | n/a | 3.99 -> 4.00 (near miss) |
| 25 others | see JSON | 0 | 0 | 0 | n/a | all < 0.4 |

Grid-only model: upguest 1/1/0 new (S1 exclusion no longer than develop's, 12:51:40-13:19:10, because 30 s ticks see
the blips as sub-tick), downguest 2/2/1 (a 0 min artefact). Edge model is the one reported above. Neither model
produces a new run on any input other than upguest.

The two Guest Bedroom 1 "new" pieces are 12 s and 0 s extensions of runs develop already excluded (17:11-18:51:40,
22:53-23:16 on 11-13), not new runs: tick-boundary effects.

## The 11-15 upguest case (edge model, CDT)

Raw (recorder): on from 07:28:19 after a 37 s off (07:27:42-07:28:19), then only 1.4-2 s blips (07:30:11, 07:34:07,
08:29:00, 08:51:19, 13:19:34, 13:51:46, 14:14:08, 14:31:26, 14:32:33), one longest on stretch 08:51:21-13:19:34. The only
gap >= 10 s inside is the 14:20:04-14:20:17 dead stretch (unavailable 6.1 s, unknown 6.6 s) and the final off 14:37:59 (324 s).

| Rule | Excluded | Note |
|---|---|---|
| Develop (tol 0) | 12:51:40 to 13:19:10 (28 min) | pops at the 13:19:34 blip; re-runs reset at every observed blip |
| S1 (tol 10 s) | 11:28:40 to 14:37:59 (about 3 h 9 min) | run anchored 07:28:19; no re-arm at 13:51 / 14:14 / 14:31 / 14:32 |
| New (S1-only) time | 11:28:40-12:51:10 (83 min) + 13:19:35-14:37:59 (79 min) | one run; BLE-confirmed persons in Guest Bedroom 2: none |

Difference from the plan text: the plan predicts S1 exclusion "from 12:51:52". Replay says S1 excludes from 11:28:40,
because the run is anchored to 07:28:19, not to 08:51:21. 12:51 is where develop first excludes. Nothing else in the
prediction (no re-arm at the later blips) is contradicted. Where was everyone: Oji, Ezinne in Master Bedroom/Bath, Jaya in Jaya Bedroom
early in the window, Ziri Away (13:39, 14:19).

## Findings for the S1 build (not gate-failing)

1. Dead-stretch accounting: the code sets `_p22_off_since[s] = state.last_changed` each tick (overwrite), and
   `lc` is the CURRENT state's change time. A dead stretch that passes through two states (unavailable -> unknown -> on,
   13 s total at 14:20:04-14:20:17) is measured as the last state only (6.6 s < 10 s), so the run survives. Spec says a dead stretch >= tolerance
   ends the run (planning S1 "Unavailable / unknown"). Replay: S1 run continued through it. Worth a test/decision
   (`test_p22_unavailable_long_restarts_run` may only cover a single-state dead stretch).
2. Patio right ZV reaches 4.00 h under S1 (3.99 h develop) without crossing the line; any tolerance or tick-phase
   change could create a second new run there. No BLE person data needed: Patio location had no overlap check since no run.
3. Population is thin: in 7 days only 3 of 28 inputs ever hold a run >= 4 h under develop-or-S1 (upguest, downguest
   the two guest-bedroom ZVs, patio right). S1's real-world effect is the guest rooms, as intended.

## Files

- `/Users/okosisi/Code/universal-room-automation/.claude/tmp/s1probe_inputs.py`, `s1probe_pull_full.py`, `s1probe_sim2.py`
  (JSON outputs alongside; the recorder pull is not committed).
