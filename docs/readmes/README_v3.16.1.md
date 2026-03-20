# URA v3.16.1 — House State ARRIVING→GUEST Deadlock Fix

## Overview
Hotfix for house state getting permanently stuck on "arriving" when unidentified persons (guests) are detected by census. The v3.15.1 guest mode feature introduced a state machine deadlock: the inference engine would try to transition ARRIVING→GUEST, but GUEST is not a valid transition from ARRIVING, causing every inference cycle to fail silently.

## Root Cause
`StateInferenceEngine.infer()` in `presence.py` checked for unidentified persons (guest detection) before checking for the ARRIVING→HOME_* transition. When `unidentified_count > 0` and `current_state == ARRIVING`, the engine returned `HouseState.GUEST`. But `VALID_TRANSITIONS[ARRIVING]` only allows `{HOME_DAY, HOME_EVENING, HOME_NIGHT, AWAY}` — GUEST is not valid. The state machine rejected the transition every cycle, and the ARRIVING→HOME_* check (which comes later in the code) was never reached.

## Fix
Removed `HouseState.ARRIVING` from the guest detection check (line 389). ARRIVING always transitions to HOME_* first; guest detection fires on the next inference cycle (~60 seconds later). This preserves the intended flow: arrive → settle → detect guests.

## Impact
- House state was stuck on "arriving" for 2 days, causing downstream effects on HVAC presets, security armed state, and notification routing
- All coordinators that gate behavior on house state (HVAC, Security, NM) were operating as if household was in transit

## Changes
- `domain_coordinators/presence.py`: Removed ARRIVING from guest detection candidate states
- `quality/tests/test_presence_coordinator.py`: 2 regression tests (arriving+unidentified→HOME_DAY, HOME_DAY+unidentified→GUEST)

## Tests
1,114 passed (2 new), 16 pre-existing DB test failures (unrelated)

## Bug Class
This is Bug Class #18: **State machine transition mismatch** — inference engine proposes a state that the state machine doesn't accept as valid, causing silent rejection loops. Prevention: any new state added to inference rules must be checked against `VALID_TRANSITIONS` for all candidate `current_state` values.
