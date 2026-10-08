# URA v5.103.41 — HVAC W1-C P2 option C: ecobee comfort select by default

Tier 3: two plan reviews, four framing-disjoint build reviews (A/B/C/D) + fix pass + D re-pass (SHIP), orchestrator mutation spot-check. Card: HVAC-W1C-GENERIC-THERMOSTAT-1.

## Problem
Option B (v5.103.40) always held URA's own range on an ecobee, so the ecobee's own Home/Sleep/Away comfort numbers were never used — unlike Bryant, where URA picks the activity and the thermostat's stored numbers apply.

## Solution
- **Default (Branch S):** URA selects the ecobee comfort setting (Current Mode select: home/sleep/away; wake → home) through a new governed funnel `emit_select_comfort` (one `climate_write` row, comfort-delay gate). The ecobee runs its own numbers.
- **Range hold (Branch R) only when needed:** Custom Preset Ranges or DPM numbers for that preset, freeze active, Vacation numbers differing from Away, unmapped presets, or no select entity. Upgrade/downgrade between S and R happen in one write.
- **Person changes:** after a 180 s settle window (operator ruling), the settled legs become the reference; any later deviation reads `manual` and goes through the arrester; settle is taken as of the window end (read-order independent). S1/vacancy re-asserts respect person-protection gates (a/b, c, e).
- Arrester reference is per requested preset; off-heat_cool reads keep the held label; persisted `Held` v2 with migration from v5.103.40.
- Repair text recommends ecobee Hold Action "Until I change it" and turning off the ecobee's own schedule (URA runs the schedule).
- Carrier byte-identical (168 goldens). Branch D (writing ecobee comfort numbers) parked until a unit exposes those entities.

## Live validation (prospective)
- Main house: no Carrier climate_write changes; no errors from hvac_strategy/hvac_setpoint.
- Wigton (after updating Wigton URA to 5.103.41, Hold Action "Until I change it", schedules off): supervised walk on Downstairs — select home/sleep/away, person change → manual, restart recovery; restore afterwards.
