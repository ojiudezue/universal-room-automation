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

## Validated 2026-09-18 (post-restart, running v5.103.12)

| Criterion | Result | Observed |
|---|---|---|
| `pre_cool_skip_reason` live on the mode sensor | **PASS** | attribute present on `sensor.ura_hvac_coordinator_mode`; moved `boot` → `no_constraint` with fresh `last_evaluate` (10:14) — set + updating each tick. |
| Mutation authority | **PASS** | orchestrator drill: renaming `"outside_window"` in source → `test_outside_window` REDs; restored. |
| No behavior change | **PASS** | `pre_cool_active` unchanged; return values byte-identical (string-set-before-return). |
| Zero URA ERROR | **PASS** | (per boot log; obs is additive). |

**The obs immediately earned its keep:** it surfaced that post-restart the predictor sees
`constraint=None` (`no_constraint`) while the EC's own sensor shows a real `normal` — i.e. the HVAC
coordinator hasn't received an `EnergyConstraint` object this boot (EC dispatches on *change* only;
mode unchanged since boot). That would leave Path A pre-cool effectively disabled from boot until the
first mode change (evening coast) on a restart day. Pre-existing signal-delivery behavior, not this
cycle — carded as `HVAC-PRECOOL-NO-CONSTRAINT-POST-BOOT-1`.

## Rollback
`git revert` — additive attribute, no state impact.
