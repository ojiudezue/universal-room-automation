# v3.8.7 — HVAC Config Flow Review Fix

## Summary
Fixes AC reset timeout config not being wired through to OverrideArrester.

## Bug
The v3.8.6 config flow exposed `CONF_HVAC_AC_RESET_TIMEOUT` in the UI, but:
- `__init__.py` didn't read it or pass it to the constructor
- `HVACCoordinator.__init__` didn't accept it
- `OverrideArrester` used the hardcoded `AC_RESET_STUCK_MINUTES` constant directly

The config value was saved but silently ignored.

## Fix
- `OverrideArrester.__init__` now accepts `ac_reset_timeout` parameter
- Uses `self._ac_reset_timeout` instead of hardcoded constant in `check_ac_reset()`
- `HVACCoordinator.__init__` accepts and forwards `ac_reset_timeout`
- `__init__.py` reads `CONF_HVAC_AC_RESET_TIMEOUT` from CM config and passes it through

## Files Changed
- `domain_coordinators/hvac_override.py` — configurable AC reset timeout
- `domain_coordinators/hvac.py` — forward ac_reset_timeout param
- `__init__.py` — read and pass AC reset timeout config
- `const.py` — version bump to 3.8.7
