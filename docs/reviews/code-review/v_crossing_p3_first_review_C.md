# Review C (Tier 3): crossing vision P3 first set, test authority by source mutation

Branch feature/crossing-p3-first @ 3925c18f (parent 340bfe7f). Sites: P3-D1, P3-D5, P3-D8 + fix-ups.
Method: 117 single-site real source mutations (own enumeration from the diff, not the builder's list), one at a time,
`python -B`, `__pycache__` purged before each run, restore in try/finally, `git status` clean afterwards.
Test set per run: test_crossing_vision_p3_first, _shadow, test_crossing_ledger, _ledger_wiring, test_crossing_vision_setup_wirein,
test_person_awareness_layer_guard, test_census_trust_golden, test_camera_stream_health, _s2 (baseline 521 passed, 1 skipped).
Scratch driver: .claude/tmp/p3c_mutdrill.py (untracked, not committed).

Result: 117 mutations, 92 RED (a specific named test fails), 25 + 3 GREEN-class rows listed below (6 extra X2 rows: 2 RED, 4 GREEN).
All REDs name the intended test (error text, scrub x3 patterns, truncate, empty-reply never 0, DAO bounds/outcome set/error-vs-empty,
cap hold, call-time gate, rehydrate timeout/retry/page/teardown/midnight/old-day, P3-D8 three conditions, kill switch,
stuck-client set, P22 hold states + fail-closed unknown manager, multi-room all-fold, last-good kept on death, cap 93, max_tokens 4000).

## GREEN rows

| # | site (file:line at 3925c18f) | mutation | class | sev | test needed |
|---|---|---|---|---|---|
| 100 | coordinator.py `_house_state_value` `getattr(presence,"house_state","") or None` | drop `or None` (empty-string house_state read as a known state, P22 releases) | TEST GAP, fail-closed path | MEDIUM | presence present with house_state "" (and None) -> `camera_input_room_stuck_excluded` P22 returns holding |
| 101 | coordinator.py `_house_state_value` except branch | return "away" on read error | TEST GAP, fail-closed path | LOW | house_state property raising -> P22 holds |
| 35 | crossing_vision.py schedule-time gate `_calls_counted() + _waiting()` | use raw `_calls_today` | TEST GAP (defense in depth; call-time gate test is RED so no call leaks) | LOW | crossing during hold records skipped_cap immediately, not `waiting` |
| 45, 58, 59 | crossing_vision.py retry `asyncio.sleep(RETRY_S)`; const RETRY_S 60 | sleep removed / RETRY_S 0 / 6000 | TEST GAP (retry spacing never asserted) | LOW | assert the second attempt waits RETRY_S (fake clock) |
| 57 | const.py CAP_REHYDRATE_TIMEOUT_S 30 | 300000 | TEST GAP (value pinned only via monkeypatch) | LOW | pin the default |
| 105 | camera_stream_health.py `input_room_stuck_excluded` fold | `answers[-1]` instead of all() | TEST GAP (two-room test has one ordering) | LOW | parametrize room order (True,False) and (False,True) |
| 96, 97 | coordinator.py listed-keys loop | drop occupancy / drop motion list | TEST GAP (only one list key exercised for False-vs-None) | LOW | input listed under each of motion/mmWave/occupancy, not excluded -> False |
| 4 | crossing_vision.py `if err is not None else None` | always stringify | TEST GAP | LOW | error row with no error text stores None, not "None" |
| 8 | crossing_vision.py key= pattern IGNORECASE | case-sensitive | TEST GAP | LOW | `Key=`/`KEY=` scrub case |
| 55 | crossing_vision.py setup create-task failure branch | state stays pending / counter not bumped | TEST GAP (diag only) | LOW | patch async_create_background_task to raise; assert state failed + hold kept |
| 115 | same branch | hold released on task-create failure | TEST GAP, hold fail-open | LOW | same test, assert `_cap_hold` True |
| 78 | crossing_vision.py map-unavailable reset of `_held_ignored_stuck` | reset removed | TEST GAP (stale diagnostic) | LOW | held_ignored_stuck empties when map becomes unavailable |
| 72 | crossing_vision.py outer `except` around `input_room_stuck_excluded` | fail open | TEST GAP (inner wrapper already fails closed; outer reachable only if `_room_coordinators` raises) | LOW | patch input_room_stuck_excluded to raise |
| 110 | sensor.py recorder-exclusion attr `crossing_vision_cap_rehydrate` | removed | TEST GAP (display attr only) | LOW | optional |
| 116 | stuck page entity tuple `("house",)` | `()` | TEST GAP | LOW | assert page scope |
| 23 | database.py upper bound column `ended_at < ?` -> `started_at < ?` | | TEST GAP (fixtures have started==ended side) | LOW | row started 23:59:55 ended 00:00:05 next day |
| 32 | crossing_vision.py `_count_today_calls` database None -> (0, True) | releases hold with no DB | TEST GAP | LOW | no database -> hold stays |
| 20 | database.py empty outcomes -> (0, False) | | EQUIVALENT in production (CALL_OUTCOMES non-empty); LOW test gap | LOW | optional |
| 9 | const.py ERROR_TEXT_MAX_CHARS 200 -> 2000 | | EQUIVALENT: the llmvision adapter already cuts at 200 upstream, so the 250-char test is masked | - | - |
| 40, 41 | rehydrate `max(self._calls_today, count)` | `count` | EQUIVALENT: no call can be made while the hold is on, so `_calls_today` is 0 | - | - |
| 53, 114 | torn_down re-checks inside rehydrate | removed | EQUIVALENT: teardown cancels the task (RED test), re-check is belt and braces | - | - |
| 70 | D8 return `held - ign, dead_held` | dead_held not subtracted | EQUIVALENT: ignored inputs are live `on` with no stream view, never in dead_held | - | - |
| 109 | camera_stream_health.py `if not input_eid` guard | removed | EQUIVALENT: no room lists "" so answers is empty -> False | - | - |
| 78/112 | rehydrate top `_roll_day()` removed | | EQUIVALENT: the ok-branch `_roll_day()` (RED) does the day check that matters | - | - |

## Findings

- No production defect found. Every gap is a test gap on a site that behaves correctly today.
- MEDIUM (1): #100. The "unknown house state fails CLOSED" rule is asserted for the no-manager path only. A present presence coordinator whose `house_state` is empty falls to the fail-open branch if `or None` is lost. One short test.
- LOW (15): listed above; none lets a wrong value reach an actuator or a vision call (the call-time cap gate and the dead/stream-view holds are mutation-anchored).
- Bug class for the gaps: #62 hollow/absent anchor (value pinned by monkeypatch, branch untested), not #53.

## Verdict: FIX-REQUIRED (test-only, small)

Add the #100 test (MEDIUM) and fold the LOW tests into the same fix-up where cheap (#101, #35, #105, #96/97, #115, #45/58 with a fake clock, #4). No source change required. Re-run the named rows after the tests land.
Counts: 117 mutations; RED 92; GREEN 25 (11 test gaps worth fixing, 14 LOW/EQUIVALENT as classified); tree clean.
