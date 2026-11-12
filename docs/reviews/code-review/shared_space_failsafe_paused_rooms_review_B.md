# Review B — SHARED-SPACE-AUTO-OFF-FAILSAFE-1 option A (failsafe in paused rooms)

Branch `fix/shared-space-failsafe-paused-rooms-r` = origin/develop + cherry-picks of e3e44a5f (build) and
d0f67ed8 (review A). Cherry-pick applied clean. Framing B: async / lifecycle / race / restart + cross-coordinator.
Not HVAC or presence work (occupancy is consumed, not changed), so the state-of-play docs were not required.

**Review A's process HIGH is resolved:** the operator explicitly picked option A on 2026-11-12, superseding the
10-18 "no lights off when paused" ruling for this failsafe only.

## Structure verified

| Check | Result | Evidence |
|---|---|---|
| Hoisted call outside `_is_automation_enabled()` gate | yes | coordinator.py:5536-5544, after the if/elif/else at :5289/:5320 |
| Exactly once per tick | yes; old in-gate call removed (comment only at :5421-5425) | read + `test_unpaused_room_exactly_one_call_per_tick` |
| Skip-first kept | `_skip_first_this_tick` captured at :5281 before the branch clears it | `test_skip_first_tick_does_not_call_failsafe` |
| ManualMode kept | `_get_room_switch_state("manual_mode") is not True` | `test_manual_mode_on_blocks_failsafe` |
| Config refresh kept | `self.automation._refresh_config()` before the call (paused rooms never hit :5402) | read |

## Async / lifecycle

- No new timers, listeners or background tasks. The only task is the pre-existing `activity_logger.log` via
  `hass.async_create_task` (automation.py:4559); unchanged.
- Own try/except, so a raise in the temperature-fan handler no longer skips the failsafe (improvement).
- Restart at or after 23:00: tick 1 is skip-first (no call); later ticks wait for presence boot-settle,
  which fails closed (automation.py:4499-4514). `_last_auto_off_date` is RAM-only, so a restart inside the window
  can sweep a second time on the first settled vacant tick. That is pre-existing behaviour, now also in paused
  rooms. LOW, no fix.
- Override Occupied / Vacant: shape `data[STATE_OCCUPIED]` at coordinator.py:5240-5256 before the hoisted site, for
  paused rooms too. Override Occupied blocks the sweep; Override Vacant makes it fire on the first in-window tick.
- House sleep: neither the old site nor the body reads house state. Nothing dropped.
- Scope: body returns unless `CONF_SHARED_SPACE` (automation.py:4531). Non-shared rooms cannot be swept.

## Findings

**HIGH — manual-ON hold defeats the failsafe in paused rooms (the Kitchen case).**
automation.py:4690 (`light_hold_allowed(lights, "off")`) + automation.py:4553 (night marked done after any sweep).
ON holds are released only by `handle_occupancy_change` (automation.py:1372-1373), which runs only inside the
enabled branch (coordinator.py:5320-5326). The reconciler still books holds in paused rooms
(actuator_reconciler.py:500-523: needs only occupied + non-URA context). Repro, legal config: Kitchen paused,
shared_space on, auto-off hour 23, `DEFAULT_LIGHT_MANUAL_ON_HOLD_S=3600` (const.py:1275). 22:50 a person turns
the overhead on by hand while occupied → hold until 23:50. 22:55 they leave. 23:00 first vacant tick: sweep skips
the held light, turns off the rest, sets `_last_auto_off_date`. The overhead stays on all night. In a paused room
hand-switching is the normal way lights come on, so this is the main path, not an edge.
`test_h5b_failsafe_sweep_via_check_scheduled_auto_off_spares_held_light`
(quality/tests/test_lighting_slice_c_manual_hold.py:423) pins this sparing behaviour, so the fix is a design call
and was not applied here. Options:
1. At the hoisted site, when the room is paused and this tick is vacant, call
   `self.automation.release_light_holds_on_vacancy()` before the failsafe. This mirrors what an enabled room does
   on its vacancy edge. h5b stays green because it calls the body directly.
2. In the body, release ON holds once the vacancy and settle gates pass. This matches the oracle's own rule
   ("until the room counts as empty") but means rewriting h5b.
Recommend option 1.

**MEDIUM — paused because sensors miss people.** The only guards are `data[STATE_OCCUPIED]` (sensors + BLE +
override), presence boot-settle, a live ON hold, and once per night. The escape is documented config:
turn on Override Occupied for the room (blocks the sweep), turn ManualMode on (blocks it), or turn
`shared_space` off for that room. The README must list these and the rooms that become eligible
(review A's list: Kitchen, Kitchen Hallway Garage, Staircase, Patio, Receiving Room, Garage A, Garage Hallway,
Exercise Room, Foyer).

**LOW — restart inside the window can sweep twice** (RAM-only night key). Pre-existing.

## Tests and drill

- Targeted: 8 files (new file, shared_space_auto_off_failsafe, lighting_slice_c_manual_hold,
  hvac_batch_d_shared_space_fans, night_light_off_path, paused_room_gates, v4515, v4516): **155 passed**.
- Mutation (bytecode off, `__pycache__` cleared): hoisted `await self._run_shared_space_failsafe(data)` replaced
  with `pass` → **5 failed** (test_paused_room_vacant_failsafe_called_once_with_vacant,
  _occupied_failsafe_called_with_occupied, test_unpaused_room_exactly_one_call_per_tick,
  test_skip_first_tick_does_not_call_failsafe, test_paused_room_vacant_in_window_real_body_sweeps). Restored;
  `git status` clean.

## Verdict
**FIX-REQUIRED** — 1 HIGH (hold release in paused rooms). The structure, gates, lifecycle and tests hold.

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| HIGH | 1 | 0 | 0 (design call to the orchestrator) |
| MEDIUM | 1 | 0 | README |
| LOW | 1 | 0 | pre-existing |

Bug classes: #53 computed-but-not-consumed (vacancy hold release lives only on the enabled path the failsafe
just left); restart, RAM-only once-per-night state.
