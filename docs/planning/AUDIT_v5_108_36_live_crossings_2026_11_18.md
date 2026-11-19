# AUDIT: v5.108.36 live crossings (P3-D2 + P3-D3), 2026-11-17 10:40 CST to 2026-11-18 23:51 CST

Source: live URA DB `memory_episodes` (read-only, `ssh ha "python3 -"`), episode_type `crossing_vision_shadow` (77 rows,
first 11-17 13:17, last 11-18 22:42) and `crossing_vision_ledger` (42 rows). Live counters:
`sensor.ura_security_coordinator_outside_open_tracks_diagnostic` attribute `crossing_vision_today`, read 11-18 23:5x CST.
Probes: `.claude/tmp/cvprobe_c.py`, `.claude/tmp/cvprobe_d.py`.

## Validated 2026-11-18

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Ambiguous crossing gets a shadow row, no ledger term | PASS (row outcome wording differs) | 33 distinct ambiguous crossing keys have shadow rows: 22 `ok` (vision analysed), 9 `clustered`, 1 `no_frigate_event`, 1 `error`. Row outcome for an analysed ambiguous crossing is `ok` with tracker `direction: ambiguous`; there is no `analysed_ambiguous` outcome string (that is an in-memory match flag, crossing_vision.py:834/1006). Ledger rows whose key is an ambiguous crossing: 0 of 33. All 41 ledger terms map to tracker entry/exit crossings and carry the tracker direction (entry-entry 17, exit-exit 17, 7 key with no shadow row). `skipped_reserved` rows: 0 |
| 2 | pipeline_version, call_kind, vision_direction, confidence, recording_window with 8 frames | PASS | 77/77 rows `pipeline_version=3`; `call_kind` primary 68, repeat 9. Every row that made a call (46 ok + 9 repeat ok + 3 error + 1 blank) is `frame_route=recording_window`, `frames_requested=8`. All 55 `ok` rows carry `vision_direction` and `vision_direction_confidence`. Values: passing 31, unclear 14, in 6, out 4 |
| 3a | calls_today under cap | PASS | cap default 93 (`const.py:3726`; no override in core.config_entries). 11-17: 17 call rows; 11-18: 35 primary calls + 7 repeats = 42. Live counter 11-18: calls 35, repeats 7 |
| 3b | repeats within budget | PASS | repeats 2 (11-17), 7 (11-18), budget 15/day (`const.py:3855`). Repeat rate ~9/68 = 13% vs 0.2 knob |
| 3c | skipped_busy on resolved crossings, skipped_reserved | 0 / 0 for 11-18; 11-17 unknown | No row in the window has outcome skipped_busy/skipped_reserved/skipped_cap. Live counters 11-18: skipped_busy 0, repeat_skipped_busy 0, skipped_reserved 0, skipped_cap 0. The counters are RAM and were reset by the 11-17 restart-to-11-18 rollover, so 11-17 counter values cannot be read; absence of rows is the only evidence. |
| 4 | Nothing acted on vision direction | PASS (ledger/rows); logs unknown | Ledger derivation unchanged: terms only on tracker entry/exit keys (see 1). `vision_amend_failed` 0 today. No crossing_vision / vision_direction lines in `docker logs homeassistant` since restart (log level likely hides them, so this is not proof). Notification text, census and `SIGNAL_EGRESS_RECORD_AMENDED` consumers were not traced live; static trace is Review D in the README. Unknown live. |

Other findings:

- Tracker vs vision direction, primary `ok` rows with tracker entry/exit (n=24): agree 4 (2 entry/in, 2 exit/out), disagree 0, vision `passing` 10, `unclear` 10 (`direction_agreement=unclear`). Vision gives a usable direction on 17% of resolved crossings.
- Ambiguous crossings (n=22 ok): vision `passing` 16, `unclear` 3, `in` 2, `out` 1 (`vision_only`).
- Operator grades (`crossing_operator_grades.json`): 0 overlapping crossing keys (grades are 11-14 crossings, rows start 11-17). Cannot score yet.
- Errors: 3 primary `Error processing video` on recording_window URLs (11-17 13:42, 13:49; 11-18 14:01), 1 `blank`, 2 `no_frigate_event`.
