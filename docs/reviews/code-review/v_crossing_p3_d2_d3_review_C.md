# Review C (test authority, per-site source mutation) — crossing vision P3-D2 + P3-D3, commit 00cd94cef

Base 056c69993. Worktree `.claude/worktrees/agent-a12740ed29a672244`. 53 independent single-site drills (runner `.claude/tmp/revC_drills_runner.py`), each run against `test_crossing_vision_p3_d2_d3.py` + `test_crossing_vision_shadow.py` + `test_crossing_vision_p3_first.py` (`-x`, drill-marked tests deselected). Tree clean and HEAD 00cd94cef after.

## RED on neuter (tested)
C2 out-of-enum direction (test_vision_direction_parsed_and_unclear_default) · C3 confidence enum · C4/C5/C6 direction_agreement branches · C11/C12 window BEFORE/AFTER (test_recording_window_url_centred_on_crossing) · C13 LAG · C14 require_complete · C18 event_clip_long · C19 route knob · C20/C21 analysed_ambiguous / shared-event counter · C22 DAO COALESCE default · C23 direction-zero re-arm · C33 repeat dedup_source_ref · C34 amendable key · C35 agreement on row · C36 dir_ok sample · C40/C41 call_kind attrs · C42/C43/C44 G3 key capture · C46 window route not event-end waiting · C47 ambiguous counter · C48/C49 req.vision/outcome stored · C51 repeat task tracking · C52 sha1 prefix · C54 window-unavailable fallback.

## GREEN on neuter (untested = findings)
| Site | Mutation | Sev | Note |
|---|---|---|---|
| C9 `_roll_day` `_repeats_today = 0` | removed | MEDIUM | day-boundary repeat budget never reset in-suite (class: day-boundary-blind) |
| C10 `_repeats_counted` cap_hold branch | disabled | MEDIUM | pre-rehydration repeat gate untested |
| C15/C16 window camera / instance `_sanitize_snapshot_token` | removed | MEDIUM | URL path-injection guard untested |
| C26 `member_inherited` payload flag | forced False | LOW | notice field untested |
| C27/C28 amend vdir / vcount gated on `analysed` | gate removed | MEDIUM | non-ok outcome could stamp stale direction on G3 record |
| C29 `req.outcome is None` guard in amend | removed | LOW | |
| C30 late-joiner `primary.outcome is not None` guard | removed | MEDIUM | |
| C31 repeat None-reply budget refund | removed | LOW | |
| C32 repeat `_enabled()` re-check | removed | MEDIUM | INV-OFF at repeat call time untested |
| C37 `_pending` includes running repeat | removed | MEDIUM | in-flight bound untested |
| C38 repeat wait deadline (`remaining <= 0`) | removed | MEDIUM | unbounded wait path |
| C39 repeat row `primary_crossing_key` | removed | LOW | |
| C45 ambiguous request joins ambiguous crossing | inverted | MEDIUM | ambiguous clustering untested |
| C50 rehydrated repeats into `_today` display counter | removed | LOW | |
| C53 repeat row `frames_requested` | removed | LOW | |
| C24 ambiguous-zero `settle` filter | removed | LOW | |
| C8 repeat_selected `<` vs `<=` | boundary | LOW | boundary only |
| C1 late-joiner ambiguous-member guard | removed | LOW | probably equivalent (ledger builds no ambiguous term); first run flaky-reported RED, rerun GREEN |
| C7 `rate <= 0` early return | removed | n/a | equivalent mutant (`h%1000 < <=0` is false) |

C17, C25 snippets matched twice (not drilled).

## Verdict: FIX-REQUIRED
Add targeted tests for the MEDIUM rows (C9, C10, C15/16, C27/28, C30, C32, C37, C38, C45) and the LOWs where cheap.
