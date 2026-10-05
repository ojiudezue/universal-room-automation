# URA v5.103.40 — HVAC W1-C P2: ecobee (HomeKit) thin adapter

Tier 2-DB + mandatory Review D (four framing-disjoint reviews), one fix pass, gap clamp. Card: HVAC-W1C-GENERIC-THERMOSTAT-1 (W1-C P2).

## Problem
The second home (Wigton) has three ecobee thermostats on HomeKit. URA's thermostat layer only knew Carrier/Bryant; other brands were gated off with `feature_available`, against the thin-adapter rule (features never gated by brand).

## Solution (option B)
- **Detection:** a HomeKit thermostat whose device manufacturer contains "ecobee" uses the ecobee adapter; other HomeKit thermostats stay Generic. Per-entity cache; an already-detected ecobee is never downgraded on an unreadable manufacturer.
- **Commands:** URA holds each preset's effective range directly (S10/Custom Preset Range for that preset this season, else the Seasonal Baseline) → guards → whole degrees (half up) → widened to the thermostat's min heat/cool gap. Never a single temperature, never the comfort-mode select, never a range outside heat_cool (defers with zero calls; Repair if heat_cool is missing or never reached).
- **New Advanced zone field:** "Min heat/cool gap" 5–10 °F, default 5 (must be ≥ the ecobee's Heat/Cool Min Delta); stored values clamped to 5–10.
- **State read:** every thermostat preset read goes through the adapter (`preset_of_for`); a person's wall/app change reads as manual, same as on Bryant. Arrester and startup audit measure against the range URA actually holds.
- **Custom Preset Ranges on ecobee:** range stored URA-side and applied while the zone is in that preset; turning CPR off restores.
- `feature_available` scaffold removed; Carrier byte-identical (168 goldens; one reviewed delta: S1 capability failure reports once instead of an ERROR per tick).
- **Follow-up:** option C (select the ecobee comfort setting by default; hold only for DPM/CPR) is planned as P2 REV 4.

## Live validation (prospective)
- Main house (Carrier only): no change in climate_write rows/sites; no ERRORs from hvac_strategy.
- Wigton has no URA HVAC coordinator enabled yet — ecobee behaviour validates when it is enabled (W1-C P3).
