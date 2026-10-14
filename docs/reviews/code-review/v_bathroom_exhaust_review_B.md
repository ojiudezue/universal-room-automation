# Bathroom exhaust — Review B (async / lifecycle / precedence / no-flap)

Branch feature/bathroom-exhaust @3fb3b3c41; base = merge-base with develop 00fb0bb6e. Targeted tests: 15 passed.

## Findings

**HIGH — callback runs off the event loop (Untracked/thread-unsafe callback).** `automation.py:3379` `_on_humidity_fan_state_change` has no `@callback` decorator and is not a coroutine. HA classifies it as `HassJobType.Executor` (`homeassistant/core.py:347-360`), so `async_track_state_change_event` (`automation.py:3328`) runs it in a worker thread. It writes `_humidity_fan_triggered_time`, `_humidity_dwell_fan_on_at` and `_humidity_fan_manual_off_until` while the loop-side tick reads and writes the same fields. Repro: the human turns the fan OFF while a tick is between `fan_is_on` (3679) and `_humidity_fan_last_asserted_at = now`. The tick sees no window and re-asserts ON inside the respect window. Tests call the handler directly (test file :420, :447), so this is never exercised. Fix: add `@callback` and import `callback` from `homeassistant.core` (line 27).

**MEDIUM — master-OFF now runs the sleep-off path (precedence).** Before this change, master OFF returned after the cap-only branch. Now sleep-off (`automation.py:3524-3561`) runs with master OFF and fires whenever `_fan_is_actually_on`. Repro: room automation OFF, non-wet room, sleep, `FAN_SLEEP_OFF`. The person turns the fan on by hand and URA turns it off on every tick. The plan's D1 decouples venting only; this is a fight with a person who opted out. Gate sleep-off on `_is_automation_enabled()`, or limit it to fans URA turned on.

**MEDIUM — the dwell can stay ON until the cap.** The dwell-OFF branch (`automation.py:3884`) needs `_humidity_presence_runtime_until`, which is armed only when `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED` is true (3696). Repro: dwell enabled, presence-runtime disabled, no humidity sensor. The fan stays on until max-runtime. That is bounded, but it is a suppression with no prompt discharge.

**LOW — the manual-OFF window is in memory only.** After a restart or reload, the window and the dwell anchor are lost. A fan left ON is re-seeded by skip-first (`automation.py:3486`) and ends normally or at the cap. A fan the human turned OFF can be re-triggered right after a restart. Acceptable; document it.

**LOW — the interim Powder automation (id 1750820778098).** Its `turn_off` carries a non-URA context, so it arms a 30-minute manual-OFF window that silences URA. Remove the automation when this ships.

**Cleared:**
- Unload teardown holds. `async_on_unload` is hooked once (3442), and the fan-list change path re-registers (3437).
- The cap still bypasses the manual window.
- `on→unavailable` is excluded.
- No-flap: raw-sensor flicker restarts the dwell timer, which is conservative. Once fired, the hold is keyed to URA's `room_occupied`. Re-assert is limited to one every 180 s.
- `fan_is_on` is anchor-based, so repeated ticks do not re-emit.
- Comfort/HVAC fan ownership: no fan-ownership code in this diff, so the existing exclusions are unchanged. A collision with a shared entity is out of scope.

## Verdict: FIX-REQUIRED
Must fix: the HIGH (`@callback`). Fix the sleep-off MEDIUM in-cycle (a few lines).
