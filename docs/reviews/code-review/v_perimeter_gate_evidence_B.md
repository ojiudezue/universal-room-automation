# Review B: PERIMETER-GATE-EVIDENCE Part A (async / lifecycle / signal chain / restart)

Branch `feature/perimeter-gate-evidence` @ `ea30b31a`, diff base = merge-base with develop `528fb5d9` (three-dot).
Plan: Part A of `docs/planning/PLANNING_perimeter_gate_evidence_and_input_health.md`. Tier 2-DB, framing B.

## Verdict: SHIP

No CRITICAL / HIGH / MEDIUM findings. Two LOW notes, neither must-fix.

## Checks

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Gate-row write is tracked | PASS | `perimeter_alert.py` `_persist_gate_decision`: `hass.async_create_task(_write())`, added to `_gate_log_tasks`, `add_done_callback(discard)`. Eager-start completion before `add` is safe: the done callback is scheduled via the loop, so it runs after `add`. |
| 2 | Alert dispatch never awaits the DB write | PASS | `_record_gate` is sync and only schedules. Probe (scratch, not committed): DB `log_memory_episode` that never returns. The alert still dispatched (`async_notify` awaited once, severity LOW) and teardown returned in <2 s with `TEARDOWN_TIMEOUT_S=0.1`, all tasks done and set cleared. |
| 3 | Exceptions never reach the alert path | PASS | `_write` catches all; schedule is wrapped in `_record_gate` try; `log_memory_episode` never raises (`database.py:10686`). `test_writer_failure_never_blocks_alert` covers raising writer, raising `async_create_task`, and missing DB. |
| 4 | Teardown latch + bounded gather | PASS | Latch set on the first line of `async_teardown` (before listener unsub and hold discharge), so the `dropped_teardown` records made by discharged holds stay in memory only. `wait_for(gather(..., return_exceptions=True), 5.0)`; timeout branch cancels leftovers; `CancelledError` (BaseException) still propagates. Teardown (`__init__.py:5888`) runs before `database.async_close()` (`__init__.py:5978`). |
| 5 | Reload | PASS | New `PerimeterAlertManager` per setup (`__init__.py:3509`), so the latch is never reused across instances. `async_setup` is the only setup call site. |
| 6 | DB unavailable at boot | PASS | `hass.data[DOMAIN]["database"]` absent means early return, no task. A worker-restart gap fails inside `_db()` and is caught. Silent loss is visible through the writer-health set (`MEMORY_WRITER_BACKED_EPISODE_TYPES` gains `perimeter_gate_decision`). |
| 7 | Write path discipline | PASS | `log_memory_episode` goes through `_db()`, the single serialized write queue (`database.py:580`). `window_dedup=False` is correct because without it the 5-min per-(node,type) window would drop real per-alert rows. Volume is a few rows per exterior alert. |
| 8 | Sun read at both D5 settle points | PASS | Pre-hold read: night means no hold, no `_dispatch_in_flight`, and `reason=night`. Post-hold re-read: sunset during the 8 s hold gives `night_after_settle` with no demote. Sunrise during the hold cannot happen because no hold starts at night (`test_sunrise_during_settle_still_no_hold_started_at_night`). Unreadable sun counts as night (`is_daylight` returns False for None). `_agreement_open` still runs before the branch. |
| 9 | D10.5 20 s path | PASS | Sun is read once, at the decision after both holds (identity wait + xcorr settle). `egress_known_person` is unaffected. The `dropped_teardown` early returns are unchanged. |
| 10 | Follow-up arming with the new reason | PASS | `egress_uncorroborated_night` was added to `_FOLLOWUP_UNKNOWN_REASONS`. Its row has `demoted=False` and `severity_after == severity`, so `_arm_identity_followup` arms. Covered by `test_egress_uncorroborated_night_arms_followup`. |
| 11 | Every `_record_gate` caller records exactly once | PASS | 10 sites: 4897 (D3 zone), 4966 + 4993 (D5 dropped / common exit; the dropped path returns), 5099 (VLM), 5335/5339/5349/5365 (D10.5 early returns), 5401 (D10.5 common exit), 5500 (follow-up). Each path reaches exactly one. Each call means one schedule, and the latch, `_active`, and missing DB suppress the row only. `test_one_row_per_record_gate_call`. |
| 12 | Downstream payload readers | PASS | `gate_decision_stats` (`sensor.py:4587`) shallow-copies `_last_gate_decisions`. The new keys (`sun_elevation` float/None, `is_day`, `would_demote_if_day`, `location`, `snapshot` basename) are JSON-safe scalars. `_arm_identity_followup` reads `at/demoted/reason/severity_after`, all unchanged. No NM payload change: severity is the only output, and it changes only as the plan specifies. |
| 13 | VLM location (D3) dark | PASS | `PERIMETER_VLM_LOCATION_ASK=False`, so `ask_location` is False and `_VERDICT_PROMPT` is sent byte-for-byte. `enrich_with_verdicts` never raises. `location` is recorded only. |

Focused tests: `test_perimeter_gate_log.py`, `test_perimeter_ss_daylight.py`, `test_perimeter_vlm_location.py`, `test_perimeter_fp_gates.py`, `test_perimeter_identity_followup.py`: 269 passed.

## LOW notes (not must-fix)

- **LOW-1 (test gap, Untracked Background Tasks class):** no committed test exercises the teardown **timeout/cancel** branch or a hung writer. I verified both with an ad-hoc probe (above). A ~20-line test would anchor them. Optional.
- **LOW-2 (pre-existing, out of diff):** `_followup_check` sends through an untracked `hass.async_create_task(self._async_send_identity_followup(...))`. It predates this cycle and is unchanged. Noted only.

## Bug-class tally

| Class | Found | Fixed | Deferred |
|---|---|---|---|
| Untracked background tasks | 1 LOW (test gap) + 1 LOW pre-existing | 0 | 2 |
