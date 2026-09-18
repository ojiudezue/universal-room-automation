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

## Validated 2026-09-18 (post-restart, running v5.103.10)

| Criterion | Result | Observed |
|---|---|---|
| 6 new display names live | **PASS** | friendly_names = `AC Runtime Cap · Coast (%) / Shed (%) / Window (min) / Enable`, `Comfort Grace · Battery Floor (%) / Duration (min)` |
| Values unchanged across rename | **PASS** | 75 / 50 / 20 / on / 85 / 20 — identical to pre-rename |
| entity_ids stable (history intact) | **PASS** | same entity_ids resolved; only `_attr_name` changed (unique_id untouched) |
| Egress knobs untouched | **PASS** | `Egress Pause Threshold` / `Egress Resume Delay` names unchanged |
| Zero URA ERROR on boot | **PASS** | system log ERROR filter for `universal_room_automation` = 0 entries |

## Rollback
`git revert` the merge — cosmetic, no state impact.
