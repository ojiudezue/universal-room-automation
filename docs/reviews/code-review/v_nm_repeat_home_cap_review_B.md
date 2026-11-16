# NM-PERIMETER-REPEAT-STORM-1 — Review B (async / lifecycle / restart / cross-coordinator)

Branch `feature/nm-repeat-home-cap` @ 6aeb12a2, diff `develop...HEAD`. Read-only. Line numbers are in the worktree `.claude/worktrees/builder-nm-repeat`.

Verdict: **FIX-REQUIRED** (2 HIGH, 1 MEDIUM).

## Findings

### B-HIGH-1: the away reset of the budget never fires in production (hollow test, Bug Class #62)
- `notification_manager.py` `_on_house_state_for_repeat_budget` reads `getattr(payload, "new_state", "")`.
- The only sender, `domain_coordinators/presence.py:9916-9925`, dispatches a **dict** (`{"old_state", "new_state", ...}`), not a `HouseStateChange` dataclass. `getattr(dict, "new_state", "")` returns `""`, so the clear never runs.
- Tests `quality/tests/test_nm_repeat_home_cap.py:393` and `:519` feed a `HouseStateChange` dataclass, so they pass against a payload shape production never sends. `routine_forecaster.py:398-403` shows the right pattern: handle both dict and attributes.
- Repro: a perimeter page is capped at 19:00 (`last_page_at` 18:00). The house goes AWAY at 20:00 and returns HOME at 22:00. A new perimeter page arrives at 23:00. The quiet time is 5 h, under the 6 h `NM_REPEAT_HOME_BUDGET_RESET_S`, so `_repeat_home_budget_blocks` returns True and the new evening gets no repeats. The plan says away starts a new session. The fallback clear inside `_repeat_home_budget_blocks` only helps when the house is *still* away at page time.
- Fix: accept a dict (`payload.get("new_state")`) as well as attributes. Make the test dispatch the real presence payload through `async_dispatcher_send`.

### B-HIGH-2: the cap can put a newer alert (life-safety included) into COOLDOWN
- `_cap_repeat_home` snapshots `data` at entry and then awaits several times: `_restore_alert_lights`, `_emit_audit_row`, the digest `log_notification` loop, `acknowledge_notification`, and `acknowledge_matching_notifications`. After that it calls `_start_cooldown()`, and `_start_cooldown` reads the **live** `self._active_alert_data` (`_start_cooldown`, ~:3896-3910).
- During those awaits, `async_notify` → `_enter_alerting` can take the slot for a newcomer. A non-life-safety slot does not hold against a newcomer, and the state is REPEATING, or ALERTING on the budget-skip path. `_enter_alerting` then schedules the newcomer's repeat. When the cap resumes, `_start_cooldown` sets COOLDOWN on the **newcomer's** data. The newcomer's pending `_repeat_alert` then returns early because the state is not REPEATING (~:3471). The newcomer's DB row is never acked, so restart recovery resurrects it.
- Repro: an unacked perimeter page reaches 60 min at HOME_EVENING, and its `_repeat_alert` fires the cap. While the audit and digest writes are in flight, a smoke CRITICAL arrives. Smoke takes the slot and its 30 s/ladder repeat is scheduled. The cap then reaches `_start_cooldown`, which puts smoke into COOLDOWN, and smoke repeats stop until cooldown expiry and re-evaluation. This breaks "life-safety unchanged". It also hits the item-1 cases "new CRITICAL of a different hazard" and "security escalation".
- `async_acknowledge` has the same snapshot-then-`_start_cooldown` shape, so the pattern predates this cycle. The cap makes it automatic and frequent, about once per hour-long page, where before it needed a rare human ack.
- Fix: capture `episode_id` at entry. After the last await, call `_start_cooldown` only if `self._active_alert_data.get("episode_id")` still matches. Otherwise leave the slot alone; the old episode's rows are already acked. A test should interleave a smoke `async_notify` inside a patched awaiting `acknowledge_notification`.

### B-MED-1: the budget is lost on a restart during the cap's cooldown
- The budget is restored only through `restore_persistence_state`. `sensor.py:9541` calls that **only when NM is IDLE**, and it is skipped when DB recovery already set COOLDOWN or REPEATING (`notification_manager.py` ~:6296-6318 resumes the cooldown through `get_active_cooldown`).
- A capped page's most likely restart state is COOLDOWN, because the cap stamps `set_cooldown`. A restart in that window recovers the cooldown and skips the whole persistence restore, so `_repeat_home_budget` stays `{}`.
- Repro: a perimeter page is capped at 19:00 and the cooldown runs to 19:30. HA restarts at 19:10. A new perimeter page at 20:00 gets a full hour of repeats.
- This fails toward paging, but it breaks the operator rule of one hour per evening. Fix: restore `repeat_home_budget` unconditionally, outside the IDLE gate, as a separate field.

### B-LOW-1: a concurrent ack during the cap double-arms the cooldown timer
In the `_repeat_alert` cap path the state stays REPEATING through the awaits, so `async_acknowledge` passes its guard. Both paths then call `_start_cooldown`. The second call overwrites `_cooldown_unsub` without cancelling the first timer. The first timer drives re-evaluation. The second finds the state is not COOLDOWN and returns. The result is one orphaned timer, missed by the teardown cancel, plus duplicate cap and ack audit rows. Nothing breaks. The B-HIGH-2 guard, or setting a non-REPEATING state at cap entry, closes this too.

### B-LOW-2: setup ordering
`_house_state_unsub` is connected in `async_setup`, before the sensor RestoreEntity pushes the budget. An away transition during boot can clear an empty dict, and the restore then reinstates the pre-restart budget. `_repeat_home_budget_blocks` re-checks the live house state, so the impact is limited to the HIGH-1 return-home case. The teardown unsub is correct (`async_teardown` ~:1500).

## Items checked and found to hold
- **Item 2, readers.** `sensor.py:15218/15230` (alert state and data), `binary_sensor.py:2954`, `house_status.py:339/353` (`get_active_criticals`), and `sensor.py:9270`. After a cap they all see COOLDOWN, then IDLE after re-evaluation, which matches the ack outcome. The panel lease is released at cap (`_panel_release_id`), so the Halo/panel stops showing the page without a human ack. That is the intended ack-equivalent end state, but note it for the operator. The ack registry is untouched, which is correct because no human acked. Audit rows are written `acknowledged=1` with `[audit]`, and `get_active_critical` and `get_active_cooldown` both exclude `[audit]` (`database.py:5148-5190`), so neither can resurrect them or shadow the real row. I did not find a security-coordinator or PWA reader of NM ack state in `custom_components`. The PWA reads entities only.
- **Re-evaluation on cooldown expiry.** `_re_evaluate_hazard` reaches `async_notify`, which reaches `_enter_alerting`, and `_repeat_home_budget_blocks` then skips repeats while the hazard persists at home. This matches the intent: the first notification sends and there are no repeats.
- **Item 4, away transition.** If the house is AWAY when the next page arrives, `_house_known_home()` returns False, the budget is cleared, and the page gets the full ladder. This holds without the signal. The return-home case is broken by HIGH-1.
- **Restart of a capped page.** Its rows are acked, so `get_active_critical` cannot resurrect it. The cooldown resumes through `get_active_cooldown`. This holds, apart from MED-1.
- **Item 5, write volume.** One audit row per resend, not per channel. Repeats happen every few minutes at most and stop after an hour at home. A cap adds one audit row, N-person digest rows, and 2 UPDATEs, once per page. All are bounded, and the writes go through the existing `log_notification` path.

## Must-fix
HIGH-1 (dict payload plus a real-shape test), HIGH-2 (episode guard before `_start_cooldown`), and MED-1 (unconditional budget restore).
