# v3.17.7 — HVAC Off-Mode Restore + Arriving State Resolution

## Changes

### Always restore thermostats from "off" mode, even during "arriving"
- The off→heat_cool restoration was inside `_apply_house_state_presets()`, entirely skipped during "arriving"
- This left zone_1 stuck in "off" mode until arriving resolved — could be 7+ minutes post-restart
- Moved the off-mode restoration loop BEFORE the arriving skip so it always runs
- Preset changes are still correctly skipped during arriving

### Fix "arriving" state stuck during sleep hours
- Inference engine tried ARRIVING→SLEEP, but the state machine correctly rejects this (not a valid transition)
- ARRIVING can only go to HOME_DAY/EVENING/NIGHT/AWAY per the state machine
- Moved the ARRIVING→time-based-home check BEFORE the sleep hours check in `infer()`
- Now: ARRIVING→HOME_NIGHT (valid), then next cycle HOME_NIGHT→SLEEP (valid)
- Previously: ARRIVING→SLEEP (rejected) → stuck on arriving indefinitely during sleep hours

## Files Changed
- `domain_coordinators/hvac.py` — off-mode restore moved before arriving skip
- `domain_coordinators/presence.py` — ARRIVING resolution before sleep check in `infer()`
