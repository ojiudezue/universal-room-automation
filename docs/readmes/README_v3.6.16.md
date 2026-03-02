# v3.6.16 — Security Coordinator Enable Toggle

**Date:** 2026-03-02
**Cycle:** Hotfix — missing UI control

---

## Summary

Adds the missing Security Coordinator enable/disable switch entity. When per-coordinator toggles were moved from config flow to switch entities in v3.6.0-c2.4, only Presence and Safety were added. Security (added in v3.6.12) was never included.

## Changes

### `switch.py`
- Added `CONF_SECURITY_ENABLED` import
- Added `CoordinatorEnabledSwitch` for Security Coordinator (`switch.ura_security_coordinator_enabled`)
- Uses `mdi:shield-lock` icon, attached to URA: Security Coordinator device

## Result

- `switch.ura_security_coordinator_enabled` entity appears under the Security Coordinator device
- Toggle on/off to enable/disable the Security Coordinator without a reload
- Matches existing pattern for Presence and Safety toggles

## Tests

590 existing tests pass. No regressions.
