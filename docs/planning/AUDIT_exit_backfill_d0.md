# AUDIT: exit-identity backfill D0 (run 2026-10-16 00:2x CDT)

Gate: docs/planning/PLANNING_egress_exit_identity_backfill.md section 4 D0. Read-only. Sources: URA DB (ssh ha, readonly) and recorder /config/home-assistant_v2.db.

## Method notes / corrections
- journald: `journalctl` is not installed in the `ssh ha` shell (command not found) and docker is permission-denied; `ha core logs` returns 401. The 0 grep lines mean "log not reachable this way", NOT "no backfills". Counters (below) prove backfills occurred.
- The census sensor is `sensor.universal_room_automation_persons_in_house` (class URAPersonsInHouseSensor, sensor.py:3641; unique_id `universal_room_automation_census_persons_in_house`), not `sensor.ura_census_persons_in_house`. It carries the ble_exit_* attrs (sensor.py:3890). Plan D0 Q3 should be corrected.
- Recorder retention begins 2026-10-08 09:12 UTC, so Q3/Q4/Q5 cover ~7.5 days, not 14. Times: URA DB timestamps are naive UTC (ISO, treated as UTC); recorder is epoch. No 5h skew applied/needed.

## Q1 (orchestrator, 14d): entry 75/279 = 26.9%; exit 59/213 = 27.7%.
Exit named by person (14d): oji_udezue 21, jaya 19, ezinne 15, ojini 4; null 154.

## (a) Face vs BLE split
Per-boot positive-delta sum of attrs over 34,600 recorder rows (14 counter resets detected; increments between last sample and a reset are lost, so these are LOWER bounds):
backfilled 11, departing_edge_seen 78, edge_no_match 19, flap_aborted 15, row_lost 2, noop 0, error 0, per_slug_cooldown_skipped 29.
Backfill increments at (UTC): 10-08 19:57, 10-09 12:33, 10-09 21:46, 10-11 14:42, 10-12 15:36 (x2), 10-13 00:33, 10-13 12:14, 10-14 10:21, 10-14 12:35, 10-15 12:37.
In the recorder window: 78 exit rows, 25 named. So BLE-backfilled >= 11 (44%), face <= 14 (56%). Pre-10-08 split of the remaining 34 named exits is unrecoverable (recorder gap; journald unreachable). All 14d: BLE >= 11 of 59.

## (b) Edge lag (6 bluetooth_le trackers: 4 Bermuda + 2 private_ble, all currently source_type bluetooth_le; 65 home->not_home edges, 0 to unavailable/unknown so miss C = 0 measured)
Signed E - nearest exit row T: <0: 8 | 0-600: 33 | 600-900: 1 | 900-1800: 3 | no row within +/-1800 s: 20.
Of the 45 edges with a nearby row, 73% fall in-window.

## (c) Recoverable ceiling (7.5d)
53 null exit rows in window; 12 have an edge in [T-300, T+1800]. Closest-edge bucket: <0: 1, 0-600: 4, 600-900: 2, 900-1800: 5. (The 4 in 0-600 are not recoverable by widening: flap/no_match/cooldown/ambiguity. Ceiling is an upper bound; edges may belong to a person other than the one who exited.)

## Verdict
- Backfill is NOT regressed: backfilled > 0 (>= 11), Q4 mass in 0-600. Discriminator = "working". Card -> done (met) after the README Validated tables; 5-row wrong-WHO spot check NOT yet done (not run here).
- R2: borderline. Letter of rule: ceiling 12 >= 10 (but over 7.5d, i.e. ~24 per 14d if rate holds) and B-side (600-1800) holds 7/12 = 58% >= 50%; no single sub-bucket does (900-1800 alone 42%). By the letter this is a narrow GO for window-widening only (BLE_EGRESS_EXIT_BACKFILL_WINDOW_S 600 -> ~1800 or a post-INSERT-anchored bound), worth about +7 named exits per 7.5d (~+3pp of 213 exits/14d to ~+6pp) against added wrong-WHO surface. Recommend the operator decide; my lean is PARK with trigger, per marginal-benefit rule, unless identity coverage for 6.0.0 needs the points.
- Open: spot-check 5 backfilled rows vs BLE history; write Validated tables into README_v5.96.1/5.97.1 (not done; read-only task).
