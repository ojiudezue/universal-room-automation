# Bathroom exhaust (occupancy + resend): Review C, test authority

Branch `feature/bathroom-exhaust` @ 3fb3b3c41, merge-base 00fb0bb6e (develop). Per-site source mutation, one site per run, PYTHONDONTWRITEBYTECODE=1 with `__pycache__` cleared before each run. Targeted files: the new test file, intelligence_cycle, hotfix_sleep_occupied, v4621, v4623. Results are diffed against the branch's own baseline failures. Tree confirmed clean after every drill.

## Baseline: the suite is red on the branch
`test_bathroom_exhaust_intelligence_cycle.py` has 6 failures here; it passes 66/66 on the merge-base. The 4 `test_FIXF_humidity_gate_*` tests still call the old 2-arg signature. `test_FIXD_coordinator_call_site_*` greps for the removed predicate. `test_d4_non_wet_room_sleep_off_still_forces_off` asserted the old unconditional turn_off, which is now intentionally gated. All 6 are stale tests the build didn't update. **HIGH.**

## Drill table (RED = a new named test fails)
| Site | Result | Catching test |
|---|---|---|
| ON transition gate | RED | turn_on_only_on_transition |
| re-assert interval cap | **GREEN** | none |
| re-assert requires actual-off | RED | no_reassert_when_actually_on |
| manual-off window check | RED | manual_off_from_state_change_listener |
| listener old==on guard | **GREEN** | none |
| unavailable exclusion | RED | unavailable_not_manual |
| URA-context predicate | **GREEN** | none |
| listener anchor-None early return | **GREEN** | none |
| dwell threshold | RED | dwell_uses_raw_sensor_not_room_timer |
| dwell raw_sensor_live | **GREEN** | none |
| dwell cap_suppressed | **GREEN** | none |
| dwell edge anchor set | RED | dwell_fires_in_rooms_without_humidity_sensor |
| dwell timing = raw ON-run (elapsed forced huge) | **GREEN** | none |
| dwell-hold short-circuit | RED | dwell_hold_blocks_humidity_off_while_occupied |
| dwell-OFF branch | RED | dwell_off_when_window_expires_no_humidity |
| presence arming, non-wet | **GREEN** | none |
| sleep-off transition gate | RED | sleep_off_no_spam_when_already_off |
| cap-off transition gate | **GREEN** | none |
| absolute None-guard | RED | dwell_disabled_no_fire |
| spike None-guard | **GREEN** | none |
| OFF-branch None-guard | RED | dwell_off_when_window_expires |
| early-return None-guard | RED | dwell_fires_in_rooms_without_humidity_sensor |
| handler toggle3 re-couples master | **GREEN** | none |
| gate fn ignores skip | RED | venting_enabled_signature_drops_automation_arg |
| skip_first early return | RED | FIXD_master_off_no_anchor_no_actuation |
| coordinator caller re-adds `_is_automation_enabled()` (D1) | **GREEN** | none |
| URA ctx on turn_on | **GREEN** | none |
| listener registration | **GREEN** | none |
| async_on_unload teardown | **GREEN** | none |
| sleep-off skip_first gate | **GREEN** | none |
| None clears cap latch | **GREEN** | none |
| dwell edge needs `not fan_is_on` | **GREEN** | none |

17 of 32 sites are untested.
- **HIGH:** the D1 caller, URA-ctx predicate + ctx stamping (an own write would arm manual-off), dwell timing source (Rev2 #4), re-assert interval, presence arming in non-wet rooms (Rev2 #3), listener registration and teardown.
- **MEDIUM:** the rest.

## Config surface
The dwell enable/seconds fields are present in the config flow, options (`_get_current`), strings.json and en.json. There is **no test** for the options round-trip or for the strings. **MEDIUM.**

## Open items from review B
- Missing @callback: no test would catch it.
- Sleep-off running with master off: the caller drill shows it is unanchored.
- Dwell-OFF without presence_runtime: no test.

The fixes for these need their own tests.

**Verdict: FIX-REQUIRED.**
1. Update the 6 stale tests.
2. Add behavioral tests for every GREEN HIGH row, driving the coordinator caller with master off.
3. Add an options round-trip test.
