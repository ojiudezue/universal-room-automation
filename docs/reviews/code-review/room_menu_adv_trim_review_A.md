# ROOM-TYPE-TRIMMED-MENU-1 (advanced trim + drop room rate) — Review A

Framing A: local correctness, edge cases, consumer completeness. Diff 884c98e2..745dab09.

## Findings
| Sev | Site | Finding | Class |
|---|---|---|---|
| LOW | coordinator.py:63,66 | `CONF_ELECTRICITY_RATE`, `DEFAULT_ELECTRICITY_RATE` imports now unused (only reader was deleted `_get_electricity_rate`). | leftover import |
| LOW (pre-existing) | sensor.py:116-117 | same two imports unused; predates diff. | leftover import |

## Cleared
- `_get_effective_rate_kwh` signature: every caller is `(hass)` — sensor.py:957, coordinator.py:5614, hvac_override.py:6624, aggregation.py:922/3243/3893/3982/4043/4063/5450/5456/5496/5502. Test stubs use `lambda *a, **kw` or `(h)`; no `room_entry=` caller remains except the TypeError-asserting test.
- No reader of the stored room `electricity_rate` remains (grep of CONF_ELECTRICITY_RATE: remaining uses are integration-level — config_flow.py:1714, 4773 global_sensors, __init__.py:5623 migration, energy_billing.py:81).
- `_get_electricity_rate` deletion safe: zero callers repo-wide.
- Reach-back (I2): energy step owned keys = rendered keys + `_STEP_EXTRA_OWNED_KEYS["energy"]=(CONF_ENERGY_SENSOR,)`; rate no longer rendered, so a stale stored 0.11 does not falsely reveal the energy step and is intentionally dead. No other stored setting lost a field. `show_all_settings` (config_flow.py:4593) lists `ROOM_MENU_STEPS_ALL` unconditionally; trimmed menus always append it (4409-4410).
- Trim per type (const.py:518-529): all 10 types mapped; common_area/bedroom/media_room/generic = full (no "More settings"); others trimmed. Unknown type falls back to ALL.
- Hint (config_flow.py:117): trimmed → type phrase + "Pick More settings for the rest." + advanced_hint(mode); untrimmed → advanced_hint(mode). Plain wording, fits label style.
- Tests: 250 passed across the 7 affected files.

## Verdict
**SHIP**. Optional: drop the two unused coordinator.py imports (1-line LOW, fix in-cycle).
