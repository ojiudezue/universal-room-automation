# v3.6.37 — Security Coordinator: NM light delegation toggle

## Summary

Added a runtime toggle (`switch.ura_security_delegate_lights_to_nm`) that controls
whether the Security Coordinator delegates light control to the Notification Manager
or drives security lights directly via ServiceCallAction.

## Problem

After v3.6.35 replaced direct light ServiceCallActions with NotificationAction
(routing through NM for light patterns), there was no way to:
- Disable NM light control if NM is not configured or unwanted
- Fall back to direct security light control
- Toggle the behavior at runtime without reloading the integration

If NM was unavailable, security alert lights silently did not fire.

## Fix

1. **Stored `delegate_lights_to_nm` flag** on SecurityCoordinator (default: True)
2. **Gated all light-related actions** in `_verdict_to_actions()` and
   `_handle_census_intent()`:
   - When ON: NotificationAction with `hazard_type` (NM handles light patterns)
   - When OFF: Direct `ServiceCallAction` for each security light + NotificationAction
     without `hazard_type` (notification still sent, just no NM light patterns)
3. **Added `_build_security_light_actions()` helper** for direct light control fallback
4. **Added `SecurityDelegateLightsSwitch`** (RestoreEntity) — runtime toggle that
   persists across restarts and syncs to the coordinator instance without reload
5. **Wired config** from `__init__.py` using `CONF_SECURITY_DELEGATE_LIGHTS_TO_NM`

## Affected Verdicts

| Verdict | delegate=True | delegate=False |
|---------|--------------|----------------|
| INVESTIGATE | NotificationAction(hazard_type="investigate") | Direct light flash + NotificationAction |
| ALERT | NotificationAction(hazard_type="investigate") | Direct light flash + NotificationAction |
| ALERT_HIGH | NotificationAction(hazard_type="intruder") | Direct light flash + NotificationAction |
| Unknown person | NotificationAction(hazard_type="intruder") | Direct light flash + NotificationAction |

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/security.py` | Store toggle, property, `_build_security_light_actions()`, gate all 3 light paths |
| `switch.py` | New `SecurityDelegateLightsSwitch` class + registered in CM entities |
| `__init__.py` | Pass `CONF_SECURITY_DELEGATE_LIGHTS_TO_NM` to SecurityCoordinator |
| `const.py` | (already had `CONF_SECURITY_DELEGATE_LIGHTS_TO_NM` from v3.6.35) |
