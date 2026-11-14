# Review C - perimeter gate evidence (test authority, real per-site source mutation)

Branch feature/perimeter-gate-evidence, HEAD 47579bac (code at e10b3128). Reviewer: C (mutation).
Method: 38 independently chosen single-site mutations of production source (perimeter_alert.py,
perimeter_fp_gates.py, perimeter_enrichment.py), one at a time, run against the four focused files
(test_perimeter_gate_log, test_perimeter_ss_daylight, test_perimeter_vlm_location,
test_perimeter_fp_gates; baseline 241 passed), `-x -m ""`, PYTHONDONTWRITEBYTECODE=1, __pycache__
cleared before and after each run, restore in try/finally. `git status --short` clean after.
Drill script (scratchpad, not committed): drillC_perim.py.

## Site x test x RED-on-neuter

| # | Site neutered | Result | First failing test |
|---|---|---|---|
| M01 | is_daylight None -> day | RED | gate_log::test_row_carries_sun_state_for_every_gate[None] |
| M02 | is_daylight except -> True | RED | fp_gates::test_is_daylight_threshold_and_none[abc-0.0-False] |
| M03 | is_daylight >= -> > | RED | ss_daylight::test_daylight_threshold_boundary[0.0-1] |
| M04 | D5 pre-settle night gate off | RED | gate_log::test_one_row_per_record_gate_call |
| M05 | D5 post-settle night gate off | RED | ss_daylight::test_sunset_during_settle_not_demoted |
| M06 | D5 post-settle reuses pre-settle is_day | RED | ss_daylight::test_sunset_during_settle_not_demoted |
| M07 | D10.5 night gate off | RED | ss_daylight::test_egress_uncorroborated_night_not_demoted |
| M08 | D10.5 flag logic inverted | RED | same |
| M09 | night reason dropped from follow-up set | RED | ss_daylight::test_egress_uncorroborated_night_arms_followup |
| M10 | D10.5 night still demotes | RED | ss_daylight::test_egress_uncorroborated_night_not_demoted |
| M11 | D5 night path leaves would_demote True | RED | ss_daylight::test_night_g5_protect_only_not_demoted |
| M12 | _record_gate never persists | RED | gate_log::test_d5_and_d6_same_alert_two_rows |
| M13 | persist twice per call | RED | same |
| M14 | persist exception propagates out of _record_gate | RED | gate_log::test_writer_failure_never_blocks_alert |
| M15 | write task not tracked | RED | gate_log::test_teardown_gathers_inflight_write |
| M16 | torn_down check removed | RED | gate_log::test_teardown_latch_alone_blocks_rows |
| M17 | _active check removed | RED | gate_log::test_no_row_before_setup |
| M18 | LOG_PERSIST flag ignored | RED | gate_log::test_persist_off_no_calls |
| M19 | teardown latch never set | RED | gate_log::test_setup_after_teardown_rearms_latch |
| M20 | setup re-arm removed | RED | same |
| M21 | teardown wait removed | RED | gate_log::test_teardown_gathers_inflight_write |
| M22 | teardown wait unbounded | RED | gate_log::test_hung_writer_never_blocks_alert_and_teardown_cancels |
| M23 | row started_at local not UTC | RED | gate_log::test_row_started_at_is_utc |
| M24 | dedup_source_ref=True | **GREEN** | none |
| M25 | window_dedup=True | RED | gate_log::test_d5_and_d6_same_alert_two_rows |
| M26 | row always re-reads sun (ignores is_day in d) | **GREEN** | none |
| M27 | write-task exception not swallowed | **GREEN** | none |
| M28 | _sun_reading except -> day | **GREEN** | none |
| M29 | ask_loc ignores master flag | RED | vlm_location::test_ask_off_prompt_identical[shadow] |
| M30 | ask_loc ignores enforce gate | RED | vlm_location::test_enforce_keeps_verdict_prompt_until_parity |
| M31 | enrich ignores ask_location | RED | same |
| M32 | enrich off-path parses with location parser | RED | vlm_location::test_ask_off_prompt_identical[shadow] |
| M33 | location STREET alters D6 severity | RED | vlm_location::test_location_never_demotes_enforce |
| M34 | parse_vlm_verdicts empty-desc guard | **GREEN** | none (equivalent mutant, see below) |
| M35 | location read from any line | RED | fp_gates::test_parse_vlm_verdicts_table |
| M36 | location line left in description | RED | vlm_location::test_shadow_asks_location_and_records_it |
| M37 | location dropped from row | RED | vlm_location::test_location_recorded_in_gate_row |
| M38 | no-op control (old == new) | GREEN | expected |

## Invariants

- INV-DAY (daylight): every demote site (D5 pre-settle, D5 post-settle, D10.5) and the None / unreadable
  / exception branches of is_daylight are RED-on-neuter with a named test. Sunset-during-settle is
  pinned by M05/M06 (the re-read is load-bearing, a stale pre-settle is_day is caught). PASS.
  Caveat: the stated invariant is "sun <= 0.0 never demotes"; the code and test pin elevation exactly
  0.0 as DAY (`>=`, test_daylight_threshold_boundary[0.0-LOW], M03 RED). Documented as the design
  ("on the horizon = daylight") but it contradicts the "<= 0.0" wording in the review brief. LOW,
  operator wording decision: if "never after sunset" is meant literally at exactly 0.0, change
  `>=` to `>` and flip that one test row.
- INV-ROW (one row per _record_gate call, never blocking): one-per-call (M12/M13/M25), never raises
  (M14), tracked + bounded teardown (M15/M21/M22), latch and re-arm (M16/M19/M20), active gate (M17),
  flag (M18). PASS with the gaps below.
- INV-LOC (D3 never changes severity, byte-identical off): M29-M33, M36, M37 RED. PASS.

## Untested sites (findings)

- LOW M24 `dedup_source_ref=True`: the tests use a fake database, so the real
  `log_memory_episode` dedup semantics are never exercised, and only `window_dedup=False` is
  pinned. A collision requires an identical (cam, gate, microsecond UTC stamp) so practical risk is
  nil, but INV-ROW "one row per call" is not pinned against the real DAO. Fix: assert the kwargs
  (dedup_source_ref is False) in the existing row test, or one real-DB row-count test.
- LOW M27 write-task exception swallow: a raising writer is only proven non-blocking, not
  non-leaky. Without the except the failure becomes a "Task exception was never retrieved" log, not
  a dispatch impact. Test could assert the task completes without an unretrieved exception.
- LOW M26 row sun fields re-read vs carried (`"is_day" in d` branch): untested; effect is a row
  whose sun_elevation could differ by seconds from the decision's. Observational only.
- INFO M28 `_sun_reading` except branch: equivalent in practice because
  `lighting/darkness.py::_read_sun_elevation` (line 64) is itself non-raising for None hass,
  states.get errors and bad attributes; the wrapper is defense in depth.
- INFO M34 is an equivalent mutant (empty desc falls through to a line scan that returns UNSURE).

## Verdict

SHIP. No HIGH/MEDIUM. Every load-bearing site for the three invariants is RED on a specific named
test; the four LOW/INFO rows above are optional test-hardening, plus one wording question
(elevation == 0.0 is day) for the operator.
