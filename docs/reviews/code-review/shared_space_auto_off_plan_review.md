# Plan review: SHARED-SPACE-AUTO-OFF-FAILSAFE-1 (Tier 2, one adversarial pass)

Plan: `docs/planning/PLANNING_shared_space_auto_off_failsafe.md`. Reviewed 2026-11-03 against develop. Read-only.

## Enumeration (re-run, not trusted)
- `_shared_space_turn_off_all` has exactly ONE production caller, `check_scheduled_auto_off` (`automation.py:4492`). Tests call it directly: `test_hvac_batch_d_shared_space_fans.py:99/114/124`, `test_lighting_slice_c_manual_hold.py:418/527`, `test_night_light_off_path.py:228`. So D2 can be a global change and doesn't need a parameter. The vacancy exit (`automation.py:1376`, `:1660`), reconciler (`actuator_reconciler.py:966/980`), resolver (`lighting/resolver.py:264`) and Away sweep (`automation.py:837+`) all read leave-on independently and are untouched.
- `check_scheduled_auto_off` and `check_auto_off_warning` each have ONE call site: `coordinator.py:5429-5430`, inside the periodic block under `elif self._is_automation_enabled():`. That block runs on every coordinator tick (~30 s plus jitter, `coordinator.py:695`), not only in hour 23. Master-automation-off rooms never sweep, today or after the change.
- Knob prior art: there's no cutoff/end-hour knob for shared space. `CONF_SHARED_SPACE_AUTO_OFF_HOUR` is at `const.py:81` and `config_flow.py:12634`. `CONF_SLEEP_END_HOUR` (`const.py:1542/3379`) has different semantics, so don't reuse it. NEW is justified.

## Findings

**HIGH-1: the vacancy source isn't specified, and the plan's stuck-exclusion claim is wrong at night.** The automation object holds no occupancy. The established pattern is for the coordinator to pass `data.get(STATE_OCCUPIED, False)` as an argument (`coordinator.py:5418-5421`, `handle_temperature_based_fan_control`). `coordinator.py:2908` is only the kill-switch predicate. Promoting a sensor to `stuck_sensors` is DEFERRED while the house is SLEEP / WAKING / HOME_NIGHT (`coordinator.py:2961`, `_d2_house_state_allows` at 2324). So a sensor that sticks after bedtime is NOT excluded during exactly the 23:00–05:00 window, and the room reads occupied all night. That falls inside the accepted trade ("false occupied = no sweep"), but the plan's justification is factually wrong.
*Fix:* D1 should say "pass `data[STATE_OCCUPIED]` from `coordinator.py:5429` as a parameter: `check_scheduled_auto_off(occupied)` and `check_auto_off_warning(occupied)`". Correct the stuck claim in "Operator decisions", and note that night stuck sensors suppress the sweep by design.

**HIGH-2: the "cutoff == auto-off hour" semantics contradict the window math.** `[h, h)` is an empty interval, so a literal builder gives "never sweep", not "today's one hour". D1 says the window may wrap, and the wrap test `start <= hour or hour < cutoff` gives "always eligible" when cutoff == start. Either reading is plausible, and neither matches what the plan intends.
*Fix:* spell out the predicate. If `cutoff == start`, eligible iff `hour == start`. If `start < cutoff`, `start <= hour < cutoff`. Otherwise (wrap), `hour >= start or hour < cutoff`. Window-start date = `today` if `hour >= start` else `today - 1 day` (the wrap case only). Add tests for start=0, start=23/cutoff=5, start=1/cutoff=5, and cutoff==start.

**MEDIUM-1: a restart or boot transient can fire a false-vacant sweep.** `_last_auto_off_date` is in-memory only (`automation.py:546`). Before this change a restart could re-fire only inside hour 23. With the change, a restart anywhere from 23:00 to 05:00 re-arms the sweep for six hours. A re-fire after a real sweep is mostly harmless (idempotent offs plus a duplicate activity row). The real risk is the first post-boot ticks, where occupancy can read False before sensors and BLE settle. That sweeps lights, fans and manual switches in an occupied room, for example a TV room at 23:30 after a restart.
*Fix:* gate on boot settle, reusing `_away_boot_settle_done()` (`automation.py:839`). Don't add a new timer. Accept the in-memory key, and document that a post-sweep restart can re-fire (benign).

**MEDIUM-2: the T-5 flash under D4 now warns of a sweep that will not happen.** The flash fires only when the room is occupied, and the sweep fires only when it is vacant. So every flash is followed by no sweep at 23:00. The lights go off whenever people leave, and the exit path already does that for non-leave-on lights. The flash has lost its meaning and now just bothers occupants nightly.
*Fix:* ask the operator one question: drop the flash, or keep it as an explicit "failsafe armed" cue? If kept, say so in the knob description. This is a design question, not a code one.

**MEDIUM-3: the manual-hold acceptance test is near-vacuous under the vacancy gate.** Vacancy transitions release ON holds (`automation.py:1365-1366`), and that happens before any vacant-tick sweep can see them. A held light can survive to a vacant sweep tick only if the hold exists without a transition, for example a person-ON noted while vacant. Existing `test_h5` (`test_lighting_slice_c_manual_hold.py:409`) calls `_shared_space_turn_off_all` directly and stays valid.
*Fix:* reword the test so it drives `check_scheduled_auto_off(occupied=False)` with a hold noted while vacant. The goal is to prove `light_hold_allowed` is still consulted. Don't claim the hold survives a vacancy transition.

**MEDIUM-4: the fans and switches behaviour change needs stating.** Before, fans (`automation.py:4703-4727`), auto switches and manual switches (`:4731-4754`) were forced off at 23:00 regardless of occupancy. After, they go off only on the first vacant tick, and never if the room stays occupied all night. This is acceptable and arguably better, but the plan's "Non-goals" makes it sound like nothing changes.
*Fix:* add one line under D1: "fans/auto/manual switches inherit the vacancy gate; an all-night-occupied room no longer forces them off". Add one regression test that a vacant sweep still respects `fan_owner`/`_fan_hvac_owned_elsewhere`. The existing tests call the method directly, so they don't cover this through the new gate.

**LOW-1: replace the literal key.** `automation.py:4681` uses the string literal `"lights_leave_on_when_empty"`. The constant `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` is already imported at `:52`. D2 deletes these lines. The plan should say to delete lines 4680-4682 and update the docstring and comments that cite "Review A MEDIUM", so a builder doesn't leave a dangling half-filter.

**LOW-2: check the existing leave-on test.** `test_lighting_slice_c_manual_hold.py:476` (`test_b_leave_on_light_stays_on_at_vacancy`) and `:574` (`test_d3_turn_off_includes_leave_on...`) touch leave-on next to the shared sweep. The builder must check whether either asserts the shared-sweep exemption. If one does, flipping it is intended (D2); it is not a regression.

**LOW-3: the activity-log description must change.** The description string "at {auto_off_hour}:00" (`automation.py:4504`) becomes wrong. Log the actual fire time, because the Live criterion keys on "first vacant time after 23:00".

## What the builder will most likely get wrong
1. The window predicate at cutoff == start, and the wrap date key (HIGH-2).
2. Reading occupancy from somewhere other than the tick's `data[STATE_OCCUPIED]`, for example re-deriving it from sensors or from `binary_sensor` state (HIGH-1).
3. Leaving the half-filter at 4681, or adding an unneeded `include_leave_on` parameter (LOW-1; there is one caller).
4. No boot-settle gate (MEDIUM-1).

## Verdict
**FIX-IN-PLAN before build:** HIGH-1, HIGH-2, MEDIUM-1, MEDIUM-4. MEDIUM-2 needs one operator answer. Then dispatch.
