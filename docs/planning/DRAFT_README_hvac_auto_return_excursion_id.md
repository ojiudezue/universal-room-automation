# DRAFT README section — HVAC-CLIMATE-WRITE-EXCURSION-ID-GAPS-1

Fold into the release that merges `fix/hvac-auto-return-excursion-id` (e2dc7c2d2).

## What changed
- When a borrowed thermostat preset is handed back automatically (`_auto_return`, `hvac_excursion.py` ~717) or restored by the startup audit (~1187), the climate-write ledger row now carries the excursion's id. Before, every `auto_return:*` row had `excursion_id` NULL (live 9/9), so those writes could not be tied back to the borrow that caused them.
- Ledger-only change: no thermostat behaviour changes. No production code reads `climate_write.excursion_id` today.

## Known residual (not fixed, recorded on the card)
- The boot ramp-audit nudge restore (`hvac_override.py` ~7739/7762) still writes NULL: the nudge registry has no id column, so fixing it needs a schema addition.

## Evidence
- Wire-in test `test_auto_return_forwards_excursion_id_to_emit_set_preset_mode` (test_hvac_excursion_d1_auto_release.py); call-neuter drill RED then restored (10-01).
- Full-suite name-diff vs develop 2b6f94bdc: identical failing-name sets (152 failed / 3 errors pre-existing), +1 passing.
- Reviews: A (local correctness) SHIP, B (consumers/completeness) SHIP.

## Live acceptance (after deploy)
- `SELECT reason, excursion_id FROM climate_write WHERE reason LIKE 'auto_return:%' AND ts > '<deploy time>';` — every row has a non-NULL `excursion_id`. Discriminates: under the old code the same query returns NULLs.
