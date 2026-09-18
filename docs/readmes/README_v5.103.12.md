# v5.103.12 — Path A pre-cool skip-reason observability

**Card:** `HVAC-PRECOOL-SKIP-REASON-OBS-1` · Tier 1 (additive attribute, no behavior change)

## Problem
Path A (the sole afternoon solar-banking pre-cool, `_should_energy_precool`) exposed positive state
(`pre_cool_active`, `pre_cool_likelihood`, zones) but **no "why it did NOT fire" signal**. With the EC
`pre_cool` vestige deleted (v5.103.11), Path A is the only path and is surplus-only — so a hot low-SOC
morning that silently skips (the `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1` case) was invisible.

## Solution
`_should_energy_precool` now sets `self._pre_cool_skip_reason` at every exit and it's published on
`sensor.ura_hvac_coordinator_mode` as **`pre_cool_skip_reason`**:

| Gate | reason |
|---|---|
| eligible / firing | `""` |
| no constraint | `no_constraint` |
| off-season (not summer/shoulder) | `off_season` |
| outside [10,14) window | `outside_window` |
| not exporting PV | `no_pv_surplus` |
| EC not in normal mode | `mode_<mode>` (e.g. `mode_coast`) |
| daily-once already fired | `already_today` |
| SOC unknown on a cool day | `soc_unknown_cool_day` |
| SOC below floor | `soc_below_floor` |

**No logic change** — a string is set before each existing return; return values are byte-identical.
Doubly useful: this is the measure-first signal `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1` needs (count
`no_pv_surplus` skips on hot days → its revival trigger).

## Validation — prospective
- **Verify:** `sensor.ura_hvac_coordinator_mode` carries `pre_cool_skip_reason`; at a normal off-peak
  hour it reads `outside_window` (before 10) or `no_pv_surplus`/`soc_below_floor` etc., not empty.
- **Verify:** zero URA ERROR on boot; `pre_cool_active` behavior unchanged.

## Rollback
`git revert` — additive attribute, no state impact.
