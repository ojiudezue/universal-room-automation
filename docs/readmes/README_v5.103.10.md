# v5.103.10 — HVAC knob labels: clearer, non-truncating

**Cycle:** `HVAC-KNOB-LABEL-PASS-1` · Tier 1 (display-name only, no logic)

## Problem
Newer HVAC knobs skipped the established naming convention and carried jargon that truncated in the
HA slider list — `D5 Duty-Cycle Coa…`, `Comfort-Delay SO…`. "D5"/"duty-cycle" is internal jargon;
"SOC" is unexplained.

## Solution
Renamed **6 entity display names only** (unique_id / entity_id / history preserved — cosmetic):

| entity | old | new |
|---|---|---|
| `…d5_duty_cycle_coast_pct` | D5 Duty-Cycle Coast (%) | **AC Runtime Cap · Coast (%)** |
| `…d5_duty_cycle_shed_pct` | D5 Duty-Cycle Shed (%) | **AC Runtime Cap · Shed (%)** |
| `…d5_duty_cycle_window_minutes` | D5 Duty-Cycle Window (minutes) | **AC Runtime Cap · Window (min)** |
| `…hvac_d5_duty_cycle_enable` (switch) | HVAC D5 Duty-Cycle Enable | **AC Runtime Cap · Enable** |
| `…comfort_delay_soc_floor` | Comfort-Delay SOC Floor (%) | **Comfort Grace · Battery Floor (%)** |
| `…comfort_delay_grace_minutes` | Comfort-Delay Grace (minutes) | **Comfort Grace · Duration (min)** |

**Deliberately NOT renamed** (operator correction): `Egress Pause Threshold` / `Egress Resume Delay`
— they concern opening egress windows (venting), not occupant exit; the names stay.

## Validation — prospective
- **Verify:** the 6 entities show the new display names in the HA UI; entity_ids unchanged (history intact).
- **Verify:** `number`/`switch` states + values unchanged across the rename (75/50/20/on/85/20).
- **Verify:** zero URA ERROR on boot.

## Rollback
`git revert` the merge — cosmetic, no state impact.
