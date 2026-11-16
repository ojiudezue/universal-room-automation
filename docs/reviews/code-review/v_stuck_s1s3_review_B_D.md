# Review B + D: stuck-sensor truth S3a / S3b / S1

Branch `feature/stuck-sensor-s1-s3`, diff `c67b8a78...HEAD` (4 commits, 4a444954 head). Reviewer framing: B
(integration, lifecycle, cross-coordinator) plus a short D (adversarial INV-S1). Read only. Read in full first:
PLANNING_stuck_sensor_truth.md rev 2 (S1/S3a/S3b), SENSOR_FLEET_CLASSES.md; PRESENCE state of play for the sections
the diff touches (exclusion set, chatter, P22).

## Verdict: FIX-REQUIRED (one gate; no code defect at HIGH+)

Must-fix before deploy:
1. **Run plan step 0 (S1 go/no-go replay).** The README says it was not run
   (`docs/readmes/README_vTBD_stuck_sensor_truth_s3a_s3b_s1.md`, "Pre-deploy gate NOT yet run"). The plan makes it the
   GO gate (`PLANNING_stuck_sensor_truth.md:212`). It is the only evidence that S1 cannot vacate a room on a real
   person (finding B-1). S3a and S3b can ship without it if S1 is held back or shipped with the knob at 0.

## Findings

| # | SEV | Where | Finding / repro | Class |
|---|---|---|---|---|
| B-1 | MEDIUM (gate) | `coordinator.py:2486-2514` (`_p22_stamp_tick` motion branch) feeding `_p22_stuck_sensor_set` `:2405-2411` and `_exclusion_set.promote("p22_continuous")` `:3916-3921` | S1 widens a P22 exclusion that already ends occupancy (fusion filter drops the input). Before S1 any observed off popped the run. With tolerance 10 s, a ZV/PIR that is the room's only live input and sees a person moving for 4 h with every gap < 10 s is excluded and the room vacates: lights/fan off on a person, HVAC zone vacancy through room occupancy. The exclusion releases only after an off ≥ 10 s. The ZV drops 30-70 s on a still person (fleet doc), so a seated person resets the run, but a continuously active one (exercise room, kitchen) is exactly what step 0 measures. This is the existing P22 mechanism with more reach, not new. It does not break "a dead sensor neither creates nor ends occupancy": dead stretches never create `on`, and long dead stretches pop the run (`:2507-2514`). | #53-adjacent reach widening; measure-before-build |
| B-2 | LOW | `coordinator.py:2507-2511` | Off and dead sub-stretches each overwrite `_p22_off_since`. A not-on stretch made of off(8 s) → unavailable(8 s) → off(8 s), each tick-observed, then on, measures 8 s, not 24 s, so the run is kept. That matches the INV-S1 wording ("every off and every dead stretch shorter than the tolerance") but not its intent (one not-on stretch). Repro: a Z2M availability blip in the middle of a ZV off. Effect: the run is kept up to 2-3x the tolerance (seconds). Low impact at 10 s. Fixing it needs care because the overwrite is needed for the `two_polls` case (unseen `on` between two observed offs). Document or accept. | INV wording vs intent |
| B-3 | LOW | `const.py` `STUCK_P22_OFF_GAP_TOLERANCE_S` | Large values (e.g. 3600) are legal at rung 1. While an off is shorter than the tolerance, the excluded input stays excluded (`_p22_stuck_sensor_set` ignores the current state), so a real re-trigger inside the window cannot create occupancy from that input. Rung 1 is review-only, so this is acceptable. Add one line on the knob: "keep below the ZV still-person drop time (30 s)". | knob boundary |
| B-4 | LOW (operator-accepted) | `_nm_cycle_a.py` `chatter_mode_option`; `coordinator.py:3412-3422` | S3a turns chatter `act` on live for the first time (Q-A). Master Bathroom InvisOutlet is motion-class in `presence_sensors`. If it is the room's only occupancy source and the chatter detector engages on a real person, the bathroom vacates. Accepted by the operator (Q-A). Live check: confirm the first master-bath chatter engagement against the occupant. | first-ever activation of a dormant path |

## Cleared (holds because …)

**Lifecycle / restart / reload**
- **S1 restart.** `_p22_off_since` / `_p22_last_on_tick` / `_p22_on_lc` are RAM-only (`coordinator.py:406-413`). After a
  restart, a restored `_sensor_on_since` is kept on the first `on`: `run` exists, `off_since` and `prev_lc` are None
  (`:2489-2503`), the same as develop. The MED-1 guard (`_post_restart_seen_on` plus boot settle, `:2405-2411`) is
  unchanged, and the motion branch adds to `_post_restart_seen_on` exactly as develop does (`:2484`). If the input is
  off at boot, its run lasts at most one more tolerance (10 s), then pops.
- **Persistence.** The store shape is unchanged (`_sensor_on_since` only). The save stays dirty-gated. Runs change only
  on a run start or restart, so the default path writes no more often.
- **Reentrancy.** `_p22_stamp_tick` is synchronous with no await, and runs before `reset_tick` and the P22 set
  (`:3881-3916`), the same order as develop.
- **Two rooms listing one input.** Bookkeeping is per coordinator. The anchor's house fold is unchanged.
- **Family resolution flip at boot.** An early registry miss returns `unknown` uncached (`fan_veto.py:80-110`), so the
  tolerance is 0 and the sensor uses the develop branch. The `tol <= 0` branch clears the S1 dicts (`:2478-2480`), so
  a later flip to tolerance 10 starts from clean state.
- **S3a reload loop.** The D7 migrate (`__init__.py:5066-5082`) runs only when the retired key is present: a one-shot
  write to the CM entry, unchanged by this diff. `invalidate_knob_cache()` at CM setup (`:5096`) runs after it and
  now also clears the chatter cache. `chatter_mode` is in `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (`:7934`), so a
  select write applies in place. The cache is flushed at three points: the select write (`select.py:1046-1051`), the
  integration listener before any subset check (`__init__.py:8926-8938`), and CM `invalidate_knob_cache(None)`
  (`_nm_cycle_a.py:59-63`). A read error is not cached. The select's `current_option` uses the same resolver, so it
  cannot disagree with the rooms (INV-S3a).
- **S3b tokeniser.** `FAMILY_BY_MODEL_TOKEN` has only `ms600` (`sensor_capability.py:435-437`), so the hyphen/underscore
  split cannot divert another model. Exact `FAMILY_BY_MODEL_ID` keys (e.g. `ZG-204ZV`) are matched before the token.

**Cross-coordinator forward trace (S1 exclusion readers)**
- Room fusion / vacancy: see B-1.
- Fan recheck: an excluded ZV stops cancelling a recheck and stops refreshing P24 (plan consumer table). This only
  arms existing bounded machinery and never powers a fan on.
- HVAC zone occupancy: reached only through room occupancy (B-1). There is no direct reader.
- Census / substrate: the substrate ignores room exclusions by design (STEP-EXCLUDE-4, plan S2 text). Unaffected.
- Crossing anchor P3-D8: `camera_input_room_stuck_excluded` (`coordinator.py:2915-2950`) drops `p22_continuous` in
  hold states and when house state is unknown (fail closed). Effect: the upguest ZV releases the anchor in AWAY only,
  which is the intended direction. The S2 G7 same-run check is not in this release (README), and the only exposure is
  a short anchor release in AWAY.
- Camera stream health: a separate client and quarantine path, not touched.

**S3b per-room effect (plan table).** The bit now resolves `generic_radar`. The witness set is unchanged, because the
name fallback already excluded the bit (`fan_veto.py:121-128`). Only radar-sole membership changes (recheck window
×1.5). Of the rooms that can newly take the radar recheck route, only GB1 becomes eligible, and only once unpaused.
GB2 and Media stay vetoed by `fan_control_off`. This matches the plan and the fleet doc, and stays bounded by the
existing recheck ladder.

## D: INV-S1 (falsifiable form) and attempts

> With tolerance > 0, for an input where `is_p22_motion_class` is True: the input is P22-excluded exactly when its run,
> stamped at the rising edge's `last_changed`, reaches `STUCK_P22_HOURS` with no off and no dead stretch ≥ tolerance,
> whatever the poll phase. A still holder, an unknown family, or tolerance 0 behaves byte-identically to develop.

| Attempt (legal config) | Result |
|---|---|
| Knob = 0 | PASS: early return of 0 (`:2425-2426`), develop loop body verbatim. |
| Knob large (3600) | PASS as specified; see B-3 (a knob note is enough). |
| ZK radar overridden to `pir` via `CONF_SENSOR_CAPABILITIES` | PASS: the override makes it not a still holder, but the family (radar) is not in `P22_MOTION_CLASS_FAMILIES`, so tolerance 0. |
| ZV overridden to `mmwave` | PASS: still holder, tolerance 0. |
| MS600 bit (S3b radar) / Matter MS600 (`16897`) | PASS: radar family, tolerance 0. |
| InvisOutlet / ESPHome LD2410 (unknown family) | PASS: tolerance 0. |
| Mixed room (ZV + ZK) | PASS: the ZV is excluded at 4 h and the ZK keeps occupancy. B-1 risk applies only to sole-input rooms. |
| Off unseen by any tick (sub-tick) | PASS: bounded by `lc - last_on_tick` (conservative, restarts). |
| Off (seen) → dead (seen) → off (seen), each < tol, total ≥ tol | LEAK vs intent, not vs wording (B-2, LOW). |
| Restart with open gap | PASS: bookkeeping is RAM-only, and at most one tolerance before the pop. |

Invariant checklist: INV-S1 PASS (with B-2 noted) · INV-S3a PASS · INV-S3b PASS (by registry model, no name read).

Bug classes: measure-before-build gate (B-1), invariant wording vs intent (B-2), knob boundary (B-3), dormant path
first activation (B-4). No untracked tasks, no listener leaks, and no new writes to a config entry.
