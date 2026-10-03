# DRAFT README — EC-SOC-LADDER-FULL-WIRING-1 (recommended split)

Draft for the release README (version to be assigned at deploy; PATCH bump).
Plan: `docs/planning/PLANNING_ec_soc_ladder_full_wiring.md` (split: D1 + D3 + D4, Tier 2-DB).

## What changed

- **Drain targets can no longer be written below the battery reserve (#1).**
  `BatteryStrategy._get_offpeak_drain_target` (the single drain-target decision seam)
  now returns the *effective* target: the five ordered classes
  (excellent → very_poor) are a running max anchored at `reserve_soc`; `unknown`
  (and any stray class) is floored at `reserve_soc` but not monotonised; all capped
  at 100. Every drain consumer (drain-fallback emission, DP value stamp, EV/plug
  release floor → pool, status/narration) already routes through this seam.
  Before: `reserve 10, drain_excellent 5` (legal on Number bounds) emitted an
  Enphase reserve of 5%. After: 10%.
- **Inclement recoverability uses the same floor the hold uses (#6).**
  `InclementFusion.decide` now passes `_partial_floor_value()` (= `max(reserve, floor)`)
  into `compute_solar_horizon`, so an inverted floor < reserve can no longer
  overstate permitted discharge and pick partial over full hold.
- **New status attribute** `drain_targets_effective` on
  `sensor.ura_energy_coordinator_battery_strategy`, beside the raw `drain_targets`.
- **Detection is not swallowed.** The raw `_drain_targets` dict, the inclement option,
  and `peak_buffer_target` are still what `validate_threshold_ladder` /
  `_check_threshold_ladder` / `get_status()["threshold_warning"]` read, so an inverted
  ladder still raises `threshold_ladder_violation`.
- **#2 (peak buffer > top drain) stays detect-only.** Design parked in the plan §D2.
  Revival trigger: any `threshold_ladder_violation` with code
  `peak_buffer_target_at_or_below_drain_poor` in `anomaly_log`.
- Docs: `safely_ordered_ladder` docstring, `energy_const.py` ladder comment and
  `ENERGY_COORDINATOR_MANUAL.md` point at the actual enforcement seams. No claim that
  inversions are impossible.

No new knobs, entities, CONF keys or DB changes. On the live (valid) ladder
10/15/20/30/30, reserve 10, every effective value equals its raw value.

## Invariants
- I-1: the off_peak drain-fallback DRAIN leg and the DP stamp `_offpeak_drain_branch_target`
  are never below `reserve_soc`. (HOLD leg `hold_reserve = int(soc)` is out of scope, unchanged.)
- I-2: validator/anomaly readers stay raw.
- I-3: identity on a valid ladder (incl. `excellent == reserve`, `poor == very_poor`).

## Tests
`quality/tests/test_ec_soc_ladder_split.py` (142 cases) drives `determine_mode` through the
drain-fallback across summer / shoulder / winter with the real `TOURateEngine`,
over matrix rows X1, X2, X3 (drains), X6, X9, X10, X11 × all six classes, asserting
the dispatched Enphase reserve value, the DP stamp, raw-dict preservation, the status
attr and the anomaly code. Plus `compose_release_floor` (pool path) and InclementFusion
recoverability.

## Live validation (prospective)
- `sensor.ura_energy_coordinator_battery_strategy` attr `drain_targets_effective` ==
  `drain_targets` (healthy live ladder).
- No `threshold_ladder_violation` rows after restart.
- Inclement `hold_depth` = `allow_discharge` on clear weather (no regression).

## Plan completion
| Item | Status |
|---|---|
| D0 measurement | done in plan §9 (pre-build) |
| D1 drain seam + `drain_targets_effective` | done |
| D3 inclement recoverability floor | done |
| D4 docs (#2 detect-only, parked) | done |
| D2 peak-buffer property + `peak_buffer_target_operator` | NOT built — out of split scope; parked in plan §D2 with revival trigger |
| Matrix rows X4, X5, X7, X8 and peak parts of X3/X11 | dropped — D2-only (plan review finding 3) |
| §6 shoulder 17:30 attain-dormancy test | not added — concerns the D2 peak-buffer path, untouched here |
| Review record `docs/reviews/code-review/v<ver>_ec_soc_ladder_full_wiring.md` | pending review phase |
