# URA v3.10.0 — Automation Chaining (M1)

**Date:** 2026-03-11
**Milestone:** M1 of 4 (AI Custom Automation & Automation Chaining)

## Summary

Trigger infrastructure and automation chaining — bind existing HA automations to URA room triggers. First milestone of the v3.10.x AI Automation series.

## Features

### Automation Chaining
- Bind 1 existing HA automation per trigger per room via config flow dropdown
- Chained automations fire via `automation.trigger` after URA's built-in automation completes
- Skips disabled (`off`) and unavailable automations with log warning
- Errors from `asyncio.gather` are logged, not swallowed

### Lux Trigger Detection
- New lux threshold crossing detection with 3-zone hysteresis model:
  - **Dark** zone: lux < 50 (fires `lux_dark` on entry)
  - **Mid** zone: 50-200 (buffer zone, no triggers)
  - **Bright** zone: lux > 200 (fires `lux_bright` on entry)
- Mid zone prevents flapping between dark and bright thresholds
- Only active when a lux sensor is configured for the room

### Trigger Types (M1)
| Trigger | Event |
|---------|-------|
| `enter` | Room becomes occupied |
| `exit` | Room becomes vacant |
| `lux_dark` | Lux drops below 50 |
| `lux_bright` | Lux rises above 200 |

### Config Flow
- New "Automation Chaining" option in room settings menu
- Dropdown shows all `automation.*` entities with friendly names
- "(none)" option to unbind a trigger
- Previously saved bindings pre-populate on re-entry

## Files Changed

| File | Changes |
|------|---------|
| `const.py` | `CONF_AUTOMATION_CHAINS`, lux thresholds, trigger constants |
| `coordinator.py` | `_detect_lux_trigger()`, `_fire_chained_automations()`, trigger detection in `_async_update_data` |
| `config_flow.py` | `async_step_automation_chaining()`, room options menu |
| `strings.json` | Menu label + step strings |
| `translations/en.json` | Mirror |
| `test_automation_chaining.py` | 25 new tests |

## Review Fixes

- `automation.trigger` skips disabled automations (`state == "off"`)
- Lux trigger guarded by sensor existence check
- `asyncio.gather` exceptions logged instead of swallowed
- Double `hass.states.get()` TOCTOU eliminated in config flow

## Test Results

763 passed (738 existing + 25 new), 11 warnings

## Plan Reference

Full plan: `docs/PLANNING_v3.10.0_AI_AUTOMATION.md`
Next: M2 (v3.10.1) — Coordinator signal triggers + conflict sensor
