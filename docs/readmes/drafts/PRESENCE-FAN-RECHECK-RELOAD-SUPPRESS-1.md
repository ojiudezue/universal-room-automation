# PRESENCE-FAN-RECHECK-RELOAD-SUPPRESS-1 (draft)

## What changed

Changing a fan-check timing on the Presence options screen no longer reloads the Coordinator Manager. Before this, saving any of the eight timings (wait before a check, fan stop time, listening time, time between checks, checks per hour, keep HVAC off the fan, radar-only readings needed, longer wait for slow radars) restarted the Coordinator Manager and every house coordinator under it. Restarting that entry is a known watchdog risk in this house.

The fan-check state machine already reads these eight values fresh from the saved options every time it uses them (`FanRecheckManager._timing_config`). So the reload did nothing useful: a saved value takes effect at the next fan check with or without one.

The per-room "Check without Bluetooth" option is not in this set. It lives on each room's own settings, not on the Coordinator Manager.

## Tests

`quality/tests/test_fan_recheck_reload_suppress.py`: for each of the eight keys, a save goes through the real options listener, no reload is scheduled, the saved snapshot moves forward, and `_timing_config` returns the new value. A key outside the set still causes a reload.

## Live acceptance

- Open Presence options, change one fan-check timing (for example "Time between checks"), save.
- Log shows `CM options changed ... in-place apply, suppressing reload` with that key, and no `Setting up` / `Unloading` line for the Coordinator Manager entry.
- The next fan check uses the new value (e.g. a changed "Time between checks" sets the length of the next cooldown).
