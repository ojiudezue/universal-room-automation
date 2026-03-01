# Universal Room Automation v3.6.0.4 — Deploy Fix for Domain Coordinators

**Release Date:** 2026-03-01
**Previous Release:** v3.6.0.3
**Minimum HA Version:** 2024.1+

---

## Summary

Hotfix: deploy.sh only staged top-level `.py` files via `$COMPONENT_DIR/*.py`, missing the `domain_coordinators/` subdirectory. All v3.6.0.3 changes to `safety.py`, `presence.py`, and `signals.py` in that subdirectory were never committed or pushed. This caused 5 safety coordinator entities to show "unavailable" (the `SIGNAL_SAFETY_ENTITIES_UPDATE` import failed in `async_added_to_hass`).

---

## Root Cause

`deploy.sh` line 48 uses glob `$COMPONENT_DIR/*.py` which only matches top-level Python files. The `domain_coordinators/` subdirectory files (safety.py, presence.py, signals.py) were modified but never staged, committed, or pushed. The v3.6.0.2 zone presence BLE bypass changes in `presence.py` were also never deployed.

## Fix

1. **deploy.sh**: Added `$COMPONENT_DIR/domain_coordinators/*.py` to the staging glob
2. **deploy.sh**: Added `$REPO_DIR/docs/readmes/` and `$REPO_DIR/docs/*.md` to staging
3. Committed all previously-unstaged domain_coordinators changes from v3.6.0.2 and v3.6.0.3

---

## Files Changed

| File | Change |
|------|--------|
| `scripts/deploy.sh` | Add domain_coordinators/*.py, docs/readmes/, docs/*.md to staging |
| `domain_coordinators/safety.py` | v3.6.0.3 changes now deployed (anomaly fix, scoped discovery, getters, push) |
| `domain_coordinators/presence.py` | v3.6.0.2 + v3.6.0.3 changes now deployed (BLE bypass, anomaly fix) |
| `domain_coordinators/signals.py` | v3.6.0.3 SIGNAL_SAFETY_ENTITIES_UPDATE now deployed |

---

## How to Verify

1. After restart, all 5 safety coordinator entities should show actual values (not "unavailable"):
   - `sensor.ura_safety_coordinator_safety_status` → "normal"
   - `sensor.ura_safety_coordinator_safety_active_hazards` → 0
   - `binary_sensor.ura_safety_coordinator_safety_alert` → off
   - `binary_sensor.ura_safety_coordinator_safety_water_leak` → off
   - `binary_sensor.ura_safety_coordinator_safety_air_quality` → off
2. Safety Anomaly should show "disabled" (SC off) or "insufficient_data"/"learning" (SC on), not "not_configured"
3. Zone presence may now work with BLE bypass (v3.6.0.2 changes finally deployed)
