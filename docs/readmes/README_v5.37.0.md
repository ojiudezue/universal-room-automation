# URA v5.37.0 — House-State Rung 1 (dead wires fixed) + unclearable-field fix

Tier-1. First build of the operator-ratified house-state utilization roadmap
(`PLANNING_house_state_utilization.md`) + a config-flow bug found during remediation.

## Rung 1 — house state's existing intent made real (no new policy)
- energy `_get_house_state` read a NONEXISTENT `presence._house_state` (always "") →
  now reads canonical `CoordinatorManager.house_state` (NM's pattern). The GUEST
  dynamic-preset reset is reachable for the first time.
- hvac dead boot-seed via same phantom attr → seeds from `manager.house_state`.
- optimization lock-advisory literal `"night"` → `"home_night"` (enum match).
- **security now SUBSCRIBES to SIGNAL_HOUSE_STATE_CHANGED** → queues an Intent through
  its existing evaluate() pipeline, so BOTH the `CONF_SECURITY_AUTO_FOLLOW` flag
  (default OFF — no behavior change this release) AND observation mode re-gate it.
  Teardown symmetric via the existing listener list (Bug Class #50). Mutation-anchored
  flag-off proof: signal fires, zero arming calls.
- Rung 2a (auto-follow ENABLED path, Tier 2-DB) is the next cycle per the plan.

## Unclearable optional EntitySelector fix
Discovered clearing Master Bathroom's mistaken water_leak_sensor (a humidity-spike
template): an optional EntitySelector with a current-value default CANNOT be cleared —
empty is rejected, omission refills the default (true in the HA UI too). Fix: a
`clear_water_leak_sensor` checkbox in the sensors step; on save writes an explicit
EMPTY options override (value may also live in entry.data — empty options wins the
merge and is falsy at every `if leak_sensor:` guard).

## Config remediations landed alongside (options-only)
- Outside zone `zone_is_outdoor: true` — activates the dormant v5.7.0 A4 outdoor
  humidity exemption + WS-A4 presence outdoor-zone exclusion (diff-verified).
- Patio room_type: NO CHANGE — no `outdoor` room_type exists; zone flag covers it
  (room-level outdoor type noted as a #12-adjacent code decision).

## Live Validation
- H1: clean boot; zero URA errors.
- H2: `security` auto-follow still OFF → house-state changes produce no arming (flag-off
  default preserved).
- H3: post-restart, clear Master Bathroom's leak slot via the new checkbox → merged
  config shows empty; zone safety chip loses the shower-trip path.
- H4 (organic): next GUEST episode → dynamic-preset guest reset actually fires (first
  time reachable) — recorder check.
