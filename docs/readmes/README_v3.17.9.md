# v3.17.9 — AC Reset Toggle + Config Flow Hardening

## Changes

### AC Reset toggle (switch + config flow)
- New `switch.ura_hvac_ac_reset` — disable AC reset without affecting the Override Arrester
- AC reset and arrester are now fully independent controls
- Disabling mid-reset immediately restores any zone that was intentionally off
- Added `hvac_ac_reset_enabled` to HVAC config flow step
- Guard in `check_ac_reset()` respects the toggle

### AC reset restore reliability
- `_restore_after_reset` changed from `blocking=False` to `blocking=True` — ensures thermostat confirms mode change
- Off-mode restore in `_apply_house_state_presets` also changed to `blocking=True`
- Added `unsuppress()` in except block to prevent arrester suppression leak on failure

### Config flow: person-to-zone mapping hardening
- Empty input preserves existing mapping (was silently wiping to `{}`)
- JSON values validated as `list[str]` (prevents string iteration bug)
- Invalid JSON shows form error instead of silent discard
- Added `invalid_json` error string

### HVAC config flow strings review
- Labels shortened and clarified (removed jargon like "Delta", "Hysteresis")
- Descriptions rewritten as plain English explaining behavior, not implementation
- Step description shortened to concise summary

## Files Changed
- `domain_coordinators/hvac_override.py` — AC reset toggle, blocking=True, mid-reset restore on disable
- `domain_coordinators/hvac.py` — blocking=True off-mode restore, unsuppress on error, ac_reset_enabled wiring
- `domain_coordinators/hvac_const.py` — CONF_HVAC_AC_RESET_ENABLED, DEFAULT_AC_RESET_ENABLED
- `config_flow.py` — AC reset boolean selector, person-zone validation fixes, error handling
- `__init__.py` — ac_reset_enabled import + HVACCoordinator wiring
- `switch.py` — HVACACResetSwitch (RestoreEntity)
- `strings.json` + `translations/en.json` — updated HVAC strings, invalid_json error, ac_reset label

## Post-Deploy
- Turn off `switch.ura_hvac_ac_reset` to disable AC reset while investigating restore failure
