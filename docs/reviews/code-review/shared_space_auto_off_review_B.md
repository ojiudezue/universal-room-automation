# SHARED-SPACE-AUTO-OFF-FAILSAFE-1 — Review B (async / lifecycle / restart / cross-coordinator)

Branch `feature/shared-space-auto-off-failsafe` @ 01026d5d vs develop 25d52dce (three-dot).
Targeted tests: 5 files, 164 passed (.venv-ha).

Doc note: the PRESENCE state-of-play doc was not read end to end for this pass. No finding below
depends on a doc claim; every finding is checked against code at the cited line.

## Wiring (the known untested gap), confirmed by reading
- `coordinator.py:5433` passes `data.get(STATE_OCCUPIED, False)`. That value is final for the tick
  at this point: override occupied/vacant is applied at 5247-5256, and the occupancy transition
  (exit → `handle_occupancy_change`) has already run at 5329-5338. It is the same value the
  temperature fan handler gets at 5420. Correct source, correct order.
- Cadence: room tick is ~30s plus jitter (`coordinator.py:695`). The window retries every vacant tick.
- Gating: the call sits inside `elif self._is_automation_enabled()` (5327), so it does not run when
  manual_mode is ON or the automation switch is OFF, and it never runs on the skip-first refresh
  (5296). This is the existing behaviour and the right one: a paused or manual room is not swept.
- `_refresh_config()` (5409) runs before the call, so an options change to start/cutoff is read on
  the same tick.

## Findings
| SEV | Where | Finding | Class |
|---|---|---|---|
| LOW | `automation.py:841-857` + `coordinator.py:5433` | Boot-settle gate fails OPEN when `coordinator_manager` or presence is not yet registered. On a cold restart between 23:00 and 05:00, if a room's 2nd tick (~30-60s) lands before the CM entry registers presence, the gate passes. A room reading vacant then (e.g. a still person on a ZG-204ZV motion-class sensor) gets swept, leave-on lights included, while the normal exit path would NOT fire (skip-first synced `_last_occupied_state`). Window is narrow and the outcome is lights off in a room that reads empty; same fail-open direction as `fan_veto`. Accept; optional hardening is fail-CLOSED for this caller only. | Restart safety |
| LOW | `automation.py:550` (in-memory `_last_auto_off_date`) | Room options reload or restart mid-window resets the night key. A second sweep can fire that night on a vacant room. Presence settle is born released on reload (`presence.py:2633-2639`, `hass.is_running`), so it is not blocked. Offs are idempotent; the only visible effect is turning off something a person switched on after the first sweep and then walked away from, which is within the failsafe's intent. Already documented in the comment. Accept. | Restart safety |
| LOW | `automation.py:4529-4538` | Activity log uses `self.hass.async_create_task` (untracked), not `entry.async_create_background_task` as the coordinator does at 5351. Pre-existing pattern carried forward; one short write per night. | Untracked background tasks |
| INFO | `coordinator.py:5410-5446` | Exception isolation: the call shares one `try` with the cover checks, so an exception from the sweep skips `check_timed_cover_*` for that tick. The night key is stamped only after `_shared_space_turn_off_all` returns, so a raise means a retry next tick, not a lost night. `_safe_service_call` with `blocking=False` keeps that path from raising in practice. Pre-existing structure. | — |

## Cross-coordinator checks (cleared)
- **Reconciler cannot re-light leave-on after the sweep.** It acts only on an unavailable→available
  edge (`actuator_reconciler.py:461-466`). Its vacant branch resolves OFF or None, never ON
  (`_resolve_light`, 862 onward is the occupied-only ON path). Holds.
- **Manual hold.** `note_manual_light` is booked only when occupied (`actuator_reconciler.py:517`),
  and holds are released on vacancy (`automation.py:1368`). By the time the vacancy-gated sweep runs,
  `light_hold_allowed` (`automation.py:792`) normally returns everything. A hold noted while the
  room reads vacant cannot exist (517 blocks it). The comment at 4663-4664 is therefore slightly
  off, but harmless.
- **Zone vacancy sweep / away leave-on sweep.** Both independently turn off a subset; double OFF is
  idempotent. There is no ON path in either.
- **Sleep.** The sweep fires on a vacant room during sleep. Night lights go off, which matches the
  reconciler's sleep+vacant fall-through to OFF (`actuator_reconciler.py:820-851`). Consistent.
- **Fans.** Fan Mode "Off" and fans owned by HVAC elsewhere are still excluded (`automation.py:4692-4699`).
- **Removed warning.** No production caller of `check_auto_off_warning` / `_last_warning_date_hour`
  remains. `quality/tests/test_fan_layer_2_d2_fixup.py:519` still sets the dead attribute; harmless.
- **Reentrancy.** Stamp after await; overlapping refreshes would at worst double an idempotent OFF.

## Verdict: SHIP
No CRITICAL, HIGH or MEDIUM findings. The three LOWs are accept-or-optional. The coordinator
wire-in is correct but has no test; a behavioural test driving `_async_update_data` with a vacant
room inside the window would close that gap, and that belongs to Review C.
