# SAFETY-HUMIDITY-JUNK-READING-1 — README section draft

_Written 2026-09-27 as Part 3 of README_v5.103.17, but v5.103.17 shipped without this branch. Fold this into the README of whichever release merges it._

## SAFETY-HUMIDITY-JUNK-READING-1

### Problem
Some humidity sensors send a bogus reading of 0% (or 3%) for about one second while they reconnect. The safety coordinator raised a MEDIUM "Low humidity" hazard on it immediately. Three of the four low-humidity alerts since 09-12 were these junk readings (Study A 0.0% twice, Dining Room 3.0%). Humidity hazards never self-clear (carded separately: SAFETY-HAZARD-NEVER-CLEARS-1), so the 09-26 23:35 CDT blip kept `binary_sensor.ura_safety_coordinator_safety_alert` **on** and the safety status at `warning` for hours while the sensor read 46-49%.

### Fix (`domain_coordinators/safety.py`, `aggregation.py`)
- New rung-1 constant `HUMIDITY_PLAUSIBLE_MIN_PCT = 5.0` (review to change; 0 disables). Readings strictly below it are treated as absent at every humidity read site:
  - `_handle_humidity`: returns before any low-humidity / sustain / swing state, so a blip neither fires nor resets the 2-4 h high-humidity window.
  - `_process_sensor`: returns before the rate-of-change detector records the value (no poisoned rate history or persisted rate baseline).
  - `evaluate_zone_chip`: treated as None (no chip trip, no comfort-drift).
  - Whole-house `SafetyAlertBinarySensor._get_alerts`: treated as None (it had its own hard-coded `< 25` check).
- Debug log at the early returns.

### Review ledger
Build `bf134b4ec` → review A (correctness/edges/consumers) SHIP + M1 (missed house-level site) + L2 (boundary tests); review B (state/lifecycle/ripple) SHIP; four out-of-scope findings carded (SAFETY-HAZARD-NEVER-CLEARS-1, SAFETY-RATE-DETECTOR-DEAD-WINDOW-1, SAFETY-RECONNECT-ZERO-SIBLINGS-1; the observability LOW folded in). Fix-up `716ae5ce4`. 18 tests in `quality/tests/test_safety_humidity_junk_floor.py`; every guard site mutation-drilled red (builder: 6 drills; orchestrator independently re-drilled the `_handle_humidity` guard: 4 named tests red, restored green).

### Live Validation (prospective)
- **Verify (discriminating):** the deploy restart clears the current stale Study A hazard, but ANY restart would, so that is not the proof. The proof comes later: the next time `sensor.invisoutlet_b7d0_humidity` (or any humidity sensor) logs a sub-5 value in the recorder, NO new "Low humidity" row appears in `notification_log` and `sensor.ura_safety_coordinator_safety_active_hazards` does not count it. Under the old code the same recorder event produces a MEDIUM alert.
- **In-suite only:** real lows (5-25%) still fire; no real indoor RH that low is expected live.
