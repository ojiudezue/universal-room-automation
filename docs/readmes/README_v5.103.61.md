# URA v5.103.61: safety hazards clear on recovery (hysteresis + 5-min hold), life-safety re-raise always re-runs the response

Card: SAFETY-HAZARD-NEVER-CLEARS-1 (operator approved the widened rev-3 scope 2026-10-14). Plan: `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` rev 4 (plan reviews: rev-3 review FIX-REQUIRED, resolved in rev 4). Tier 2-DB: review A (correctness) SHIP, review B (lifecycle/consumers) SHIP, review C (per-site mutation, 82 sites) FIX-REQUIRED on tests, fixed. Built by ura-super-builder (life-safety). Deploy risk: **MEDIUM** (safety coordinator; nothing actuates on clear). Ships in the same restart as v5.103.60.

## Why
Humidity, temperature and rate-of-change hazards were raised but never cleared, so alert entities and counts stayed on indefinitely; binary/numeric clears were immediate, so a reading sitting on a threshold (Study A CO2 1500-1502) flapped.

## What changed
See `docs/Coordinator/SAFETY_COORDINATOR.md` §5.x. Clear lines with per-type offsets (freeze 48 F, overheat 97 F, high humidity = room "low" - 3 %, low humidity 33 %, CO2 1400, TVOC 200, CO 23; rate hazards on None or < 50 % of raise magnitude), a 300 s hold swept every minute, per-key contributor sets, comfort-type drop after 900 s unavailable, and invariant I2: a SMOKE/CO/WATER_LEAK raise during a pending clear re-runs the full response (valve, lights, HIGH page). Review A's MED fixed: a leak re-wet that escalates to FLOODING keeps its water_leak key. CO/TVOC clear lines anchor to the lowest raising rung (review A: the plan's "medium - offset" would have cleared CO above 25 and flapped). The known failing `test_safety_coordinator.py::test_tvoc_detection` is fixed (test seeded a naive datetime).

Knobs (rung 1, `safety.py` ~251-276): `FREEZE_/OVERHEAT_CLEAR_OFFSET_F` 3, `HIGH_/LOW_HUMIDITY_CLEAR_OFFSET_PCT` 3, `CO2_CLEAR_OFFSET_PPM` 100, `TVOC_CLEAR_OFFSET_PPB` 50, `CO_CLEAR_OFFSET_PPM` 2, `ROC_CLEAR_OFFSET_FRAC` 0.5, `HAZARD_MIN_HOLD_S` 300 (0 = immediate clear), `ROC_STALE_SAMPLE_S` 900, `SENSOR_UNAVAILABLE_WINDOW_S` 900.

## Tests
`quality/tests/test_safety_hazard_clear_on_recovery.py` (75 tests, literal boundaries; I2 at hold 0/1/300/86400 s). Drills: builder 52/55 red (3 green = redundant backstops), review C 66/82 red before the fix-up, its must-fix sites now red.

## Pre-deploy gate
- Full-suite name-diff vs develop 434d8f1f0: 5 NEW, all order-dependent (pass alone): the smoke-off and TVOC tests in `test_safety_coordinator.py` and `test_restart_safety_doctrine_1.py`, plus `test_safety_high_humidity_clear_follows_operator_override`. Cause: an earlier test re-imports `safety` / `_nm_cycle_a`, so the tests patched a stale module's clock and knob cache. Fixed (0069be22c) by resolving the module the coordinator actually runs in. Re-run 2026-10-15 of every file sorting before the targets plus the targets: all 5 pass; the 81 other failures are pre-existing develop failures. CLEAN.

## Live acceptance
- **Live:** a humidity/temperature hazard active before the restart clears within ~6 min of its sensor recovering (safety active-hazard count falls).
- **Live:** no smoke/CO/leak entity clears while its sensor is on/wet/unavailable.
- **Live:** 0 URA ERRORs from the safety coordinator.

## Validated 2026-10-15 (HA restart 12:44 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| Hazard clears ~6 min after recovery | Not observable yet | `sensor.ura_safety_coordinator_safety_active_hazards` = 0 at boot (12:46:12); no hazard raised since. Proven in-suite (75 tests). |
| 0 URA ERRORs | **PASS** | system_log ERROR filter `universal_room_automation`: 0. |
| Envoy healthy after restart | **PASS** | `sensor.envoy_482543015950_battery` fresh 12:46:27 (~2 min), 0 unavailable through 15:06. |
