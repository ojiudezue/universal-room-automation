# NM diag text menu: Review A (local correctness, edge cases, safety invariants)

Branch `feature/nm-diag-text-menu` @ `61992005`. Diff base verified with `git merge-base develop HEAD` = `4d9963ad`. The pre-review tag `637b0bb8` is the feature commit; `35b02d00` (WhatsApp keys) and `3eeb0b7c` (Companion person) were added after it and are reviewed here too.
Read in full before review: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (`hvac()` reads HVAC zones), `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md` (`who()` reads census and person state). Nothing in this branch contradicts either doc's corrections ledger.

## Findings

| # | SEV | Site | Finding | Bug class |
|---|---|---|---|---|
| A1 | HIGH (latent, legal config) | `notification_manager.py` `_parse_whatsapp_event` / `_handle_whatsapp_reply` (~3524-3574) | The bridge runs on the operator's own number. Every direct chat to that number has `to` = the operator and `fromMe=False`; recorder: 222 of 1704 events. The parser accepts all of them and attributes each to whichever NM person the `from` number matches. Today only `person.oji_udezue` is configured, so all 222 are ignored. Repro under legal config: add Jaya as an NM person with her WhatsApp phone (the obvious way to give her WhatsApp alerts). Her ordinary chat to Oji then runs commands. "stop", "quiet" or "mute" silences non-CRITICAL alerts for 30 min. "who" or "doors" sends a house report into their personal chat from Oji's account. Any other text, with `_notifications_today_count > 0` (almost always true), gets "Unknown command. Reply: 1=Ack..." from Oji's account. Before this branch the wrong keys made the path dead, so this commit arms it, with no kill switch (`NM_DIAG_ENABLED` does not cover it). Live it buys nothing yet: 0 of 1704 events came from the operator, so the self-chat path never fires. Fix: accept WhatsApp inbound only in the self-chat (`from` digits == `to` digits == the configured person phone), or behind a rung-1 switch defaulting to self-chat-only. Get an operator ruling on direct chats. | Trust-boundary widening on a re-enabled dead path (same family as #53: the parser is fixed, its consumers' assumptions are not re-checked) |
| A2 | MEDIUM | `_send_reply` → `_send_companion(..., Severity.LOW, svc, menu_safe=True)` (~4400); `_send_companion` non-critical actions (~2366-2371) | Companion actions now produce replies (status, silence, text-input, diag). Each reply is a non-critical push, so it carries the plain **Acknowledge** button. That button runs `async_acknowledge(..., bulk_authority=BULK_ACK_TRUSTED)` with no safe word (`_handle_companion_action` ~3457). Repro: CRITICAL active → tap **Status** on the critical push → the status reply arrives with an Acknowledge button → one tap acks the CRITICAL and sweeps the backlog, no safe word. Companion is ruled trusted (C-MED-2), and other non-critical pushes already carry this button during a CRITICAL. Still, this puts a safe-word-free ack directly under the CRITICAL's own status reply, a path nobody has ruled on. Fix: send replies without actions (a `reply=True` kwarg that skips `data.actions`), or get an operator ruling. | Precedence / safety-adjacent UI path |
| A3 | LOW | `_process_inbound_reply` step-4 comment (~3816) | The comment "Companion (person None) skipped", plan LOW-10 and §2.2 no longer hold. `3eeb0b7c` resolves the Companion person, so diag now runs over the Companion text-input action. Behaviour is safe: the state rail and the send rail apply per (person, `companion`), and a CRITICAL push bumps the epoch. But plan scope said "No fix for ... the Companion no-reply gap (new card)", and `test_companion_person_none_skips_diag` now covers only the unresolved case. Fix: update the comment and the plan non-goal; add a test that a resolved Companion "1" during ALERTING goes to legacy. | Doc/plan drift (scope growth after the pre-review tag) |
| A4 | LOW | `NM_DIAG_ENABLED` docstring ("The ONLY kill switch ... byte-identical to pre-cycle") | This is no longer true for the branch as a whole. Turning the switch off restores `_process_inbound_reply`, but not WhatsApp ingestion (A1) or Companion replies and person attribution. The I4 oracle diffs `_process_inbound_reply` only, so it stays valid, but the comment overclaims. Fix: reword, and name the two transport fixes as un-switched. | Doc accuracy |
| A5 | LOW | `_resolve_diag` `int(text)` (~4119) | `str.isdigit()` is True for superscripts ("²", "³") but `int()` raises ValueError. Repro: window open, IDLE, same epoch, inbound "³" → exception in the `_process_inbound_reply` task, no reply, no log row (pre-cycle: "Unknown command"). Fix: `text.isdecimal()` (or `isascii() and isdigit()`). | Input validation |
| A6 | LOW | `_resolve_diag` closed-notice branch | A "3" meant as silence within 300 s of the person's own "diag", after any send closed the window, gets the notice and no effect. The plan accepts this by name (§2.3, MEDIUM-6). Recorded so it is not re-found. | Accepted by plan |
| A7 | LOW | `_parse_whatsapp_event` legacy branch | Any payload with a `message` or `phone` key skips the group/newsletter/broadcast filter. No such payload exists (1704 of 1704 events use the new shape), but the guard the operator asked for is bypassable by key shape. Fix: apply the `isGroup` / `@g.us` test before the legacy return. | Defence in depth |

## Cleared (holds because)

- **I1** holds. `epoch_at_entry` and `now_at_entry` are captured before the first await. The only awaits before `_resolve_diag` are in early-return branches (`_window_over_cap`, echo). The window is written only in IDLE. A digit maps only when the epoch is the same AND the state is IDLE AND age < 120 s. Every alert send goes through one of the four senders, which bump the epoch before the dry-run return; the reply path passes `menu_safe=True`. A state change without a send is caught by the state rail. Per plan §2.3, legacy 1 and 2 have no effect when IDLE (`_enter_alerting` is CRITICAL-only), so only "3" can be lost, and only in the accepted A6 case.
- **I1b** holds. `rail2=False` skips both the check and the `_last_reply_at` stamp. The safe-word check runs before diag (`is_safe_word` forces `diag=None`), so a safe word equal to a diag word still acks.
- **I2** holds for the diag branch. It reads `house_status`, writes the window and budget dicts and the counter, writes one `log_inbound` row (allowed), and sends one reply. The silenced branch is bypassed only when `diag is not None`. `house_status` makes no service calls and no DB writes. `_read_kwh_rate(warn=False)` skips the stale-warning stamp.
- **I3** holds. Matching is whole-text exact, and every reply is multi-line (`render` header plus at least one line, the multi-line menu texts, the rate-limit text). An echo with or without the title prefix cannot equal a token.
- **I5** holds. `render` reserves the suffix budget, and the cut path returns ≤ `max_chars` = 900 − 6. The static texts are short.
- **WhatsApp groups, newsletters and broadcasts** are dropped (`isGroup`, `@g.us` on `to` for own group messages, matching the bridge's own `trigger.py:43-57` note). A message the operator sends to a third party is dropped (`fromMe` with `from` ≠ `to`). Own messages carrying a LID `from` fail to match a person (fail-closed). Family group messages can never trigger silence or ack. Direct messages can: see A1.
- **Companion spoofing.** `context.user_id` is set by HA auth. An automation-fired or unauthenticated event resolves to None (pre-fix behaviour). Resolution is restricted to NM-configured persons. `_match_safe_word` still checks the global word after the personal one, so a resolved person loses nothing. Companion stays outside `NM_REPLY_RATE_LIMITED_CHANNELS`.
- **house_status answers.**
  - **doors** reads the live `security_lock_entities` (now front entry + garage hallway; master bedroom absent, matching the 2026-11-07 change). Unlocked, open, jammed, unlocking, unavailable and unknown count as problems; a missing entity shows as "not found".
  - **garage** shows SC covers plus the two lockout locks read directly (both `esphome`, registry-verified, not in the SC list). locked → on, unlocked → off, unavailable → problem.
  - **who**: HouseState `.value`; census "~N (estimate)"; `person_state_for_trust` plus `get_person_location`.
  - **hvac**: raw ZoneState fields (adapter-routed `preset_mode`, labelled "thermostat reports", which is honest per HVAC doc §4.4); the kW reader handles W→kW, kWh rejection and staleness.
  - **energy**: Envoy-tiered `battery_soc`; `net_power_w` positive = importing (`energy_battery.py:2591`), so the sign label is right; values in W converted once to kW.
  - **health**: unique_id `{entry_id}_unavailable_entities` matches the registry (47 entries).
  - Every getter is guarded, and `_build_diag_answer` catches any error.

## Verdict: FIX-REQUIRED

Must-fix:
- **A1**: restrict WhatsApp inbound to the self-chat, or get an explicit operator ruling plus a switch.
- **A2**: send replies without action buttons, or get an operator ruling.

Fix in the same pass (LOWs, 1-10 LoC each): A3 comment + test, A4 docstring, A5 `isdecimal`, A7 group filter before the legacy return.

| Severity | Found | Must-fix |
|---|---|---|
| HIGH | 1 | 1 |
| MEDIUM | 1 | 1 |
| LOW | 5 | 4 (A6 accepted) |
