# NM-PERIMETER-REPEAT-STORM-1 — Review A (local correctness + edge cases)

Branch feature/nm-repeat-home-cap @ 6aeb12a2, diff `develop...HEAD`. Read-only; no tests run (framing C owns pytest).

## Findings

### HIGH-1 — away reset listener never fires on the live payload (Bug Class #62 hollow anchor / payload-shape mismatch)
- `notification_manager.py` `_on_house_state_for_repeat_budget`: `getattr(payload, "new_state", "")`.
- The only live sender, `domain_coordinators/presence.py:9916-9924`, dispatches a **dict** (`{"old_state", "new_state", "trigger", "confidence"}`), not the `HouseStateChange` dataclass. `getattr(dict, "new_state", "")` is `""`, so the budget is never cleared by the signal.
- Tests (`test_nm_repeat_home_cap.py:389-394, :503-519`) feed `HouseStateChange(...)`, so they pass against a payload production never sends.
- Failing input: hazard `exterior_person` capped at home at 20:00 (budget used). The house goes `away` 21:00 and returns `home_evening` 22:00, with no page of that hazard while away. New page at 22:30: budget still present (last_page_at 20:00, under 6 h), so the page gets **no repeats**. Option A says away resets it. The decision-time clear in `_repeat_home_budget_blocks` only helps when a page arrives *during* away.
- Fix: accept both shapes, the way `hvac.py:5203-5208` does (`payload.get("new_state")` if dict, else attr), then `str(...).lower()`. Add a test that dispatches the dict shape.

### LOW-1 — the life-safety helper count does not see the cap site (#62)
- `_repeat_home_cap_reached` calls `is_life_safety_hazard(\n self.hass, ...)` across two lines, so `src.count("is_life_safety_hazard(self.hass,")` misses it. 14→15 counts only the `_repeat_home_budget_blocks` site. The new exclusion has a behavioural test, but the source-grep guard silently skips one of the two new sites. Put it on one line (making it 16) or note it in the test docstring.

### LOW-2 — boot read of the house state is AWAY before restore
- `_panel_house_state` (:6493) reads `cm.house_state`. `HouseStateMachine.__init__` defaults to `HouseState.AWAY` (`house_state.py:153`) until restore. A page decided in that window is treated as away: repeats continue (fails toward paging, OK), but `_repeat_home_budget_blocks` **clears every budget** (`home is False` branch). Effect: one extra hour of repeats after a restart. Acceptable; document it or skip the clear when the state machine is not yet restored.

## Cleared (holds because)
- **Knob 0:** `_repeat_home_cap_reached` returns False when cap ≤ 0; `_repeat_home_budget_blocks` returns False when cap or reset ≤ 0. Legacy ladder is preserved.
- **Life-safety:** both decision sites check `is_life_safety_hazard` first. Smoke, CO and flood are never capped or budget-blocked.
- **Unknown state:** `_house_known_home` returns None for "" (no CM) or a non-enum value. The cap returns False (`is True` check), and the budget does not block. Fails toward paging. `HouseState` is a `StrEnum` (`house_state.py:56`), so `str(enum).lower()` gives `"away"` and so on. No `HouseState.AWAY` repr issue.
- **6 h boundary:** `quiet >= reset_s` pops the entry and keeps paging. A blocked page refreshes `last_page_at` only on the block path, which matches the README. A corrupt or empty `last_page_at` makes `fromisoformat` raise ValueError, `quiet = reset_s`, and the entry resets (fails toward paging). Naive timestamps are coerced to UTC.
- **Per-hazard keying:** the key is `str(hazard_type or "")`, set in `_cap_repeat_home` only when `reason == "repeat_capped_home"`. The skip path does not re-stamp `used_at`. A hazard of None shares the "" key, which is acceptable.
- **Persistence:** saved as a dict of dicts. On restore, a missing key or a non-dict value leaves `{}`, and non-dict entries are dropped. A `None` value becomes `"None"`, which falls to the corrupt-value reset above.
- **Ack-equivalent DB step:** `_cap_repeat_home` runs the same `acknowledge_notification` + `acknowledge_matching_notifications` + `_last_acked_row_id` + `_start_cooldown` sequence as an ack. `get_active_critical`/`get_active_criticals` (database.py:5129-5170) cannot resurrect the page. `get_active_cooldown` (database.py:5187) reads `acknowledged=1` to restore the cooldown, which is the intended behaviour. No ack-registry entry, no ack TTS, no bulk sweep. In the source I read, no reader treats `acknowledged=1`/`ack_time` as "a human acked" (grep of `ack_time|acknowledged = 1` turns up only the DDL and the cooldown reader). The `repeat_capped_home` outcome row is what tells a cap apart from a human ack. Security escalation keys on NM alert state and the ack registry, not on the row flag.
- **Per-resend audit rows:** one row per resend, `message='[audit]'`, `acknowledged=1`. The `[audit]` filter excludes them from `get_notifications_today` (database.py:4878), last-notification and digest. `bucket_outcome="repeat"` is not `NM_BUCKET_NO_CHANNEL_FIRED`, so the no-route trip-wire is untouched. A resend with no channel writes `delivered=0` and is not counted as a hole. These rows do go into the in-RAM `_routing_audit_log` ring (maxlen 10). During a long away storm, resends can push routing decisions out of the D4 card. That is cosmetic.
- **Cap before send:** the check sits at the top of the repeat handler, before the `repeat_count` increment and any send, so a page restored after a restart follows the same rule.
- **`_enter_alerting`:** the first notification has already gone out. The block path calls `_cap_repeat_home(digest=False)` and returns before `_schedule_repeat`. The listener is unsubscribed in teardown.

## Verdict: FIX-REQUIRED
Must-fix: HIGH-1 (accept the dict payload and add a dict-shape test). LOW-1/LOW-2 can be fixed in the same fix-up.
