# v3.6.15 — Coordinator Manager Initialization Fix

**Date:** 2026-03-02
**Cycle:** Hotfix — regression fix
**Cross-ref:** v3.6.12 (Security Coordinator), v3.6.14 (Automation Hardening)

---

## Summary

Fixes a critical regression introduced in v3.6.12 where the entire Domain Coordinator Manager failed to initialize. A missing import (`CONF_SECURITY_ENABLED`) caused a `NameError` during startup, preventing Presence, Safety, and Security coordinators from running. Also adds the missing Security Coordinator enable/disable toggle to the config flow.

## Root Cause

In `__init__.py`, the Security Coordinator registration block at line 866 referenced `CONF_SECURITY_ENABLED`, but this constant was not included in the import block at line 806. The `NameError` was caught by the outer `try/except`, which logged the error but silently skipped storing `coordinator_manager` in `hass.data`. This caused a cascade of failures:

- All coordinator sensors showed "not_initialized" (Presence, Safety, Security anomaly sensors)
- House state override select entity showed "unavailable"
- House state sensor returned fallback "away" regardless of actual occupancy
- Presence Coordinator never ran — no house state inference, no geofence processing
- Safety Coordinator never ran — no hazard monitoring
- Security Coordinator never ran — no armed state management

## Changes

### `__init__.py`
- Added `CONF_SECURITY_ENABLED` to the import block at line 806, alongside `CONF_PRESENCE_ENABLED` and `CONF_SAFETY_ENABLED`

### `config_flow.py`
- Added Security Coordinator toggle to `coordinator_toggles` step (was missing — only Presence and Safety had toggles)

### `const.py` / `manifest.json`
- Version bump to 3.6.15

## Impact

- All three coordinators (Presence, Safety, Security) will initialize on next restart
- House state will reflect actual occupancy instead of fallback "away"
- Anomaly sensors will show real values instead of "not_initialized"
- House state override dropdown will become available
- Security Coordinator can now be disabled via config flow toggle

## Tests

590 existing tests pass. No regressions.
