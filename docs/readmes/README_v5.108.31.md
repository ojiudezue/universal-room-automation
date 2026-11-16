# URA v5.108.31: unacked perimeter pages repeat for one hour per evening at home

Card: NM-PERIMETER-REPEAT-STORM-1 (Tier 2). Operator 2026-11-16: "Paging - first hour if home. More if away", then option A (the hour is per evening at home). Reviews A and B (FIX-REQUIRED -> fixed 9eb1289d), full suite 23,112 passed, orchestrator mutation on the episode guard RED.

## What changed

- An unacknowledged non-life-safety CRITICAL page (for example a perimeter "person detected" page) still repeats every 5 minutes for the first hour.
- Past one hour, each repeat tick reads the house state first. If the house is home (any known state other than away or vacation), repeats stop and NM ends in the same state an ack reaches: the slot's rows are marked acknowledged in `notification_log`, and `_start_cooldown` runs (COOLDOWN with the hazard's cooldown minutes, `cooldown_expires` stamped on the row). A cap differs from a human ack in three ways: it writes a pre-acked outcome row (`route_reason = bucket_outcome = repeat_capped_home`), each recipient gets one digest line ("Repeats stopped: <title>"), and there is no ack-registry entry, ack TTS or bulk backlog sweep.
- Away or vacation: the existing ladder continues (30 min until 24 h, then daily).
- Unknown house state (no coordinator manager, empty, or not a `HouseState` value): repeats continue. This fails toward paging.
- Life-safety hazards (base set plus operator extras, including smoke/CO/flood on the "standard" ladder) are never capped.
- Every resend now writes one `notification_log` row (`route_reason="repeat"`, `matrix_branch="repeat_<n>"`, channels fired, pre-acked, `message="[audit]"`). Resends can now be counted. Volume is one row per resend, not one per channel: at most 11 in the first hour, then 2 per hour.
- **Home repeat budget (operator option A).** The hour of repeats is a budget per hazard per home session, not per page. Capping a page at home marks that hazard's budget used. While it is used, a NEW page of the same hazard still sends its first notification (someone new is outside) but starts no repeat chain. It ends like a cap: rows acked, COOLDOWN, and an outcome row `repeat_skipped_home_budget`, with no digest line because the page itself was delivered. The check sits in `_enter_alerting`, after the first send and before the repeat timer would start. Each new page of the hazard refreshes the budget's last-page time. The budget resets on a real transition into away or vacation, received through the `SIGNAL_HOUSE_STATE_CHANGED` listener. The listener accepts the dict that presence dispatches (presence.py:9916-9925) and the `HouseStateChange` dataclass, and it ignores payloads without a distinct old state. It also resets after `NM_REPEAT_HOME_BUDGET_RESET_S` with no page of that hazard. Budgets are per hazard: an `exterior_vehicle` page is not affected by an `exterior_person` budget. Life-safety pages are never affected, and an unknown house state keeps paging. A page that arrives while the house reads away gets the full ladder but does not clear the budget, because the state machine boots as AWAY (house_state.py:153) and a clear at decision time would wipe the budget on every restart. The budget is persisted in the NM persistence dict (`get/restore_persistence_state`, carried by the NM diagnostics sensor's RestoreEntity `nm_persistence_state` attribute, sensor.py:9538/9583), so it survives a restart. The sensor restores the budget unconditionally, outside its IDLE gate, because the cap's own cooldown is the most likely state at restart. Ordering: the listener is subscribed in `async_setup`, before the RestoreEntity push. A real away transition seen during boot records a clear time, and the restore then drops any entry whose last page is older than that, so a cleared budget cannot come back. Entries set during this boot take precedence over restored ones.
- **Slot safety.** The cap remembers the episode it started on. After its DB awaits it enters cooldown only if the slot still holds that episode in ALERTING or REPEATING. A newcomer that took the slot mid-cap (for example smoke) is left alone, and so is a slot a concurrent human ack already cooled. `_start_cooldown` now cancels any cooldown timer that is already armed, so a racing ack and cap never leave an orphaned timer.
- `exterior_vehicle`: the default perimeter severity map caps vehicles at HIGH (const.py `NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP["car"]`), so they never start a repeat chain today. If an operator promotes one to CRITICAL, the cap and the budget apply to it automatically, keyed by its own hazard.
- Ack ends the repeat exactly as before. A page restored after a restart follows the same rule at its first repeat tick, before anything is sent.

## Knobs (rung 1, `const.py`)

| Knob | Default | Notes |
|---|---|---|
| `NM_REPEAT_HOME_CAP_S` | 3600 | Age after which a home house stops repeats. 0 disables the cap (legacy ladder). |
| `NM_REPEAT_HOME_BUDGET_RESET_S` | 21600 | Quiet time, with no page of the hazard, after which its home budget resets. 0 disables the budget (per-page cap only). |
| `NM_REPEAT_CAP_AWAY_STATES` | `{"away", "vacation"}` | States that keep repeating. A separate constant from `MEMORY_WRITER_HEALTH_ABSENT_HOUSE_STATES`; the two are equal today by coincidence. |

House state is read with the existing `NotificationManager._panel_house_state()` (the same coercion `_is_quiet_hours` uses).

## Known limits

- COOLDOWN itself still does not block a new CRITICAL of a different hazard (the existing rule in `_enter_alerting`). For the same hazard at home, the budget above stops the repeat chain. When a cooldown expires, `_re_evaluate_hazard` re-fires if the source coordinator reports the hazard still active; that is the existing post-ack rule, and the re-fired page is subject to the budget.
- The repeat number restarts at 1 after a restart.

## Acceptance

- Test: `quality/tests/test_nm_repeat_home_cap.py` (44 tests, incl. the dict payload, a smoke page taking the slot mid-cap, a concurrent ack, the sensor restoring the budget during the cooldown, a boot-default AWAY, and restore-vs-listener ordering; home cap into COOLDOWN; home budget: second page sends once with no repeats, reset by the away signal, reset by a page while away, 6 h quiet boundary with refresh, knob 0, restart, life-safety, per-hazard, unknown state, setup/teardown subscription; restart after cap, new CRITICAL in cooldown, 3599 s versus 3600 s boundary, away/vacation at 1800 s, unknown state, life-safety intruder and smoke, knob 0, numbered resend rows, ack, restart home and away).
- Live: after the next unacked perimeter page with the house home, `notification_log` shows 11 `route_reason='repeat'` rows and one `repeat_capped_home` row, and no resends after one hour. A second page of the same hazard within the budget shows one first-send plus a `repeat_skipped_home_budget` row and no `repeat` rows.

## Live validation

Pending deploy.
