# v4.2.7 — Vacancy Sweep Hardening

**Date:** April 19, 2026
**Scope:** Defensive hardening of HVAC zone vacancy sweep
**Tests:** 1478 passing (no regressions)

## Changes

### Observation Mode Guard
Added explicit observation mode check at the entry of `_execute_vacancy_sweep()`.
Previously, observation mode was only checked at the call site (`_apply_house_state_presets`
is gated by `if not self._observation_mode`). The method itself had no guard,
making it fragile if ever called from a different code path.

### Error Logging
Changed silent exception swallowing (`except Exception: pass`) to warning-level
logging (`_LOGGER.warning("...failed to turn off %s: %s", entity_id, exc)`).
Service call failures were previously invisible — now they appear in the log
for diagnostics.

### Sweep Count Tracking
Added `swept_count` variable to track how many entities were actually turned off.
Info log now shows: `"Vacancy sweep for zone X — turned off N entities"` instead
of the generic `"lights and fans off"`.

### Unused Import Cleanup
Removed 4 unused imports from the method-local import block:
`CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM`. Only `CONF_LIGHTS`
and `CONF_FANS` are actually used.

## Files Changed
- `domain_coordinators/hvac.py` — `_execute_vacancy_sweep()` method hardened
