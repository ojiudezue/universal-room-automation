# NM diag text menu - Review C (test authority via real per-site source mutation)

Branch feature/nm-diag-text-menu @ 0bb31643, base 4d9963ad (merge-base verified, three-dot).
Method: 43 single-site mutations of production source (one Python script, try/finally restore,
`__pycache__` cleared + PYTHONDONTWRITEBYTECODE before every run). Test set per run = the 5 cycle
files (test_nm_diag_dispatch, test_nm_diag_menu, test_house_status, test_nm_inbound_companion,
test_nm_inbound_whatsapp) + test_nm_echo_guard; baseline 115 passed. `-x`, so the first failing test is named.
No `source_mutation`-marked drill tests exist in these files. Builder drills not trusted; all re-run.

## Site / mutation / result

| Site | Mutation | Result (first RED test) |
|---|---|---|
| epoch bump top, pushover | removed | RED test_each_sender_bumps_epoch_first_ast |
| epoch bump top, companion | removed | RED test_each_sender_bumps_epoch_first_ast |
| epoch bump top, whatsapp | removed | RED test_nm_diag_menu dry-run test (:104) |
| epoch bump top, imessage | removed | RED test_each_sender_bumps_epoch_first_ast |
| post-send close (finally), x4 | removed each | RED test_diag_opened_during_send_await_is_closed_after[pushover/companion/whatsapp/imessage] |
| step-0 epoch capture | `epoch_at_entry = -1` | RED test_closed_notice_is_read_only |
| step-0 local threaded into _resolve_diag | pass live `self._diag_send_epoch` | GREEN - provably redundant (see F4) |
| alert-active check at window open | `if True` | RED test_nm_diag_menu:132 |
| state rail in _resolve_diag | `if False` | RED test_digit_while_alerting_is_ack |
| epoch-match check | `if False` | RED test_closed_notice_is_read_only |
| rail2=False diag reply | rail2=True | RED test_doors_then_safe_word_20s_confirmation_sent |
| rail2=False rate-limit notice | rail2=True | **GREEN** (F1) |
| `not rail2` branch in _log_and_reply | branch removed | RED test_doors_then_safe_word_20s_confirmation_sent |
| safe-word-before-diag | drop `is_safe_word` | RED test_safe_word_beats_diag_name |
| silence exemption | drop `diag is None` | RED test_diag_answers_while_silenced |
| diag budget threshold | `if False` | RED test_rate_exempt_and_budget |
| budget silent-after-notice | `if False` | RED test_rate_exempt_and_budget |
| NM_DIAG_ENABLED dispatch gate | removed | RED test_kill_switch_disables_diag |
| NM_DIAG_ENABLED help-line gate | removed | RED test_help_mentions_diag_a... |
| NM_WHATSAPP_INBOUND_ENABLED | removed | RED test_kill_switch_ignores_all_whatsapp |
| WA self-chat guard (from==to) | removed | RED test_family_direct_chat_never_parsed[stop] |
| WA group filter: isGroup flag | removed | RED test_group_newsletter_broadcast_ignored |
| WA group filter: from/to suffix match | removed (isGroup only) | **GREEN** (F2) |
| WA group filter: `to` side only | removed | **GREEN** (F2) |
| WA replay dedup call | removed | RED test_replay_of_same_event_is_dropped |
| WA dedup key body component | dropped | RED test_diag_over_whatsapp_end_to_end |
| WA dedup TTL prune | disabled | RED test_replay_after_ttl_is_processed |
| WA dedup record | removed | RED test_replay_of_same_event_is_dropped |
| Companion reply=True (no actions) | branch removed | RED test_nm_inbound_companion::test_status_reply |
| _send_reply passes reply=True | removed | RED test_status_reply |
| _person_for_companion_event: status / silence / text call sites | person=None each | RED x3 (…_reaches_resolved_person, test_text_input_diag_word_answers) |
| _person_for_companion: configured-person restriction | removed | RED test_unconfigured_person_not_resolved |
| _person_for_companion: user_id match | forced true | RED test_unresolved_user_keeps_old_behaviour |
| reply cap: title-prefix subtraction | cap +1000 | RED test_reply_bounded |
| reply cap: render truncation | disabled | RED test_reply_bounded |
| reply cap: render suffix reserve | `budget = max_chars` | **GREEN** (F3) |
| read-only: service call in house_status.doors | injected | RED test_nm_diag_dispatch:236 (behavioural, plus AST lint) |
| read-only: service call in _build_diag_answer | injected | RED test_nm_diag_dispatch:236 |
| digit guard isdecimal -> isdigit | swapped | RED test_superscript... |
| window expiry check | removed | RED test_window_expiry_restores_legacy |
| closed-notice IDLE/no-active-alert conditions | removed | RED test_digit_after_critical_send_is_ack[whatsapp] |

Read-only guarantee is protected two ways (AST lint test_module_is_read_only_ast_lint, and a behavioural
no-service-call assertion that went RED on injection outside house_status too).

## Findings

- **F1 (MEDIUM, bug class #62-adjacent untested site)** notification_manager.py `_handle_diag` over-budget
  notice: `rail2=False` on the `diag_rate_limited` `_log_and_reply` is untested. Flip to True stamps
  `_last_reply_at` and the notice goes through the rail-2 rate limiter, so an over-budget notice can swallow
  or be swallowed by a later ack/safe-word confirmation, the exact I1b hazard HIGH-2 fixed for normal diag
  replies. Needs a test: exhaust budget, then safe-word within NM_REPLY_MIN_INTERVAL_S, assert confirmation
  sent and `_last_reply_at` unstamped.
- **F2 (LOW)** WA group filter: removing the `@g.us/@newsletter/@broadcast` suffix test (or its `to` half) is
  GREEN. For bridge-shape payloads this is redundant: the self-chat guard (from digits == to digits) already
  rejects a group JID against the own number. The suffix clause is only load-bearing for the legacy
  `phone`/`message` shape (checked before the legacy branch per the docstring), and that combination has no
  test. Add one legacy-shape payload with `from="...@g.us"` expecting ignore, or accept as defence-in-depth.
- **F3 (LOW)** `house_status.render` suffix reserve (`budget = max_chars - (len(suffix)+1)`) is untested: with
  the reserve removed the truncated output can exceed `max_chars` by the suffix length. Harmless at current
  numbers (900 cap vs Pushover 1024), but render's own "never exceeds max_chars" contract has no
  boundary test (lines sized to land just under max_chars with `remaining > 0`).
- **F4 (INFO, redundant)** `_resolve_diag(... epoch_at_entry ...)` vs live epoch is GREEN because no await sits
  between step 0 and step 4 on any non-returning path (the only await in that span, ~notification_manager.py
  3883-3888, is on a branch that returns). The capture itself is protected (RED when mutated). The threading
  is future-proofing, not currently observable; a race test cannot distinguish it today. Accept.
- Clean: the worktree shows only an untracked `docs/reviews/code-review/nm_diag_text_menu_review_A.md`
  that predates this review (not mine); no tracked-file modifications.

## Verdict

**FIX-REQUIRED (minor)**: add the F1 test (the only genuinely untested safety-relevant site). F2/F3 are
LOW and may ship with cards or one-line tests; F4 accepted. All other 38 sites went RED on a specific named
test, including all 8 sender-rail sites, step-0 capture, alert/epoch checks, rail2 (both halves), safe-word
ordering, silence exemption, budget, both kill switches, WA self-chat/replay, Companion reply/attribution, and
reply cap. No tree mutation left in place.
