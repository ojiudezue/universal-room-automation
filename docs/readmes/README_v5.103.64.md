# URA v5.103.64: exit naming respects the door-naming switch; Last Person Exit shows late names

Card: EGRESS-EXIT-IDENTITY-BACKFILL-1 residual R1. Plan: `docs/planning/PLANNING_egress_exit_identity_backfill.md`. D0: `docs/planning/AUDIT_exit_backfill_d0.md` (backfill working, not regressed; R2 window widening parked: 12 recoverable/7.5 days, no single miss pattern ≥50%). Tier 1: review SHIP (`docs/reviews/code-review/exit_backfill_r1_review.md`, 2 optional LOWs). Deploy risk: **LOW**. Active after the next HA restart.

## What changed
- `switch.ura_name_people_at_doors` (CONF_EGRESS_IDENTITY_ENABLED) now also gates the BLE exit backfill: read fresh in the departure handler (before the cooldown is stamped) and again just before the DB UPDATE. Skips counted in `ble_exit_identity_disabled_skip_count` on `sensor.universal_room_automation_persons_in_house`.
- "Last Person Exit" re-reads the newest exit row when a backfill names it (newest row only, camera must match, timestamp unchanged, no re-notify, no census change). New rung-1 constant `LAST_EXIT_BACKFILL_REREAD_SLACK_S = 300`. The sensor's bus listener is now unsubscribed on removal (leak fix).
- Identity manual gains §4.3a "Exit backfill". README_v5.96.1 / v5.97.1 now carry their Validated tables.

## Tests
- 5 new tests (3 backfill switch, 2 display); each fails on develop. Mutation drills: 6/6 RED.
- Full-suite name-diff vs develop 53b3ecb8f: **CLEAN**, 0 NEW / 0 GONE (119 failed / 15018 passed vs 119 / 15013).

## Live acceptance
- **Live:** with the switch on, an organic exit backfill names the row and Last Person Exit shows the name within ~5 min of the not_home edge.
- **Live:** 0 URA ERRORs after restart.

## Live Validation - Validated 2026-10-17

Window: v5.103.64 loaded 2026-10-16 15:56:39Z, HA restarted again 2026-10-17 18:24:43Z (counters reset). Sources: URA DB `person_entry_exit_events` (naive UTC), HA recorder `/config/home-assistant_v2.db` (read-only via `ssh ha`). The schema has no backfill marker (the DAO leaves `confidence` untouched, `database.py:4404`), so "named by backfill" is read from the `ble_exit_backfilled_count` attribute history on `sensor.universal_room_automation_persons_in_house`.

| Criterion | Result | Evidence |
|---|---|---|
| Exit crossings in window | as-expected (n=4) | 4 exit rows (ids 8635, 8637, 8638, 8640): 2 named at insert (8635 jaya 11:50:22Z, 8638 jaya 20:23:10Z), 0 named by backfill, 2 still NULL (8637 20:14:31Z, 8640 20:46:15Z). D0 baseline (7.5 d): 25 of 78 named, >=11 by backfill. Window is too small to compare rates. |
| `switch.ura_name_people_at_doors` | PASS | `on` since the 10-17 18:24:43Z restart; no state change in window. `ble_exit_identity_disabled_skip_count` = 0 (never needed). |
| Organic backfill names a row, Last Person Exit shows it within ~5 min | NOT OBSERVED | `ble_exit_backfilled_count` stayed 0 in both boots. Edge outcomes: 12:01Z/12:02Z edges -> `edge_no_match` 1 + `per_slug_cooldown_skipped` 1 (row 8635 already named, correctly not overwritten); 20:29Z/20:30Z edges -> `flap_aborted` 1 (20:34:16Z) + cooldown skip 1. Rows 8637/8640 stayed NULL (no valid edge). Last Person Exit history shows `unidentified` for the NULL rows and `jaya` for the insert-named rows only. In-suite only: 5 new tests, 6/6 mutation drills RED. |
| 0 URA ERRORs mentioning census/egress/backfill | UNKNOWN | No readable log from the `ssh ha` shell (journald not reachable, `/config/home-assistant.log` absent; only `.old` from Nov 2025). `ble_exit_error_count` = 0 in both boots (counter evidence only). |
| Row-level wrong-person spot check (5 most recent organic backfills, 10-13 to 10-15, pre-window; same code path, v5.103.64 adds only the switch gate and display) | PASS: 3 RIGHT, 0 WRONG, 2 UNVERIFIABLE | see below |

Spot check method: counter increment time = edge + 300 s settle; the row's `person_id` is compared with that resident's tracker `not_home` edge and the other residents' states (recorder). `sensor.universal_room_automation_persons_exited_today` history shows the row going `unidentified` -> name at the increment.

| Backfill (UTC) | Row, named | Evidence | Verdict |
|---|---|---|---|
| 10-15 12:37:12 | 8630 12:24:39 jaya | jaya Bermuda not_home 12:31:48 (lag 7.1 min), jaya private_ble 12:32:22; oji/ezinne/ziri not_home since 10-14 22:28; exited_today 12:24 `unidentified` -> 12:36:48 `jaya` | RIGHT |
| 10-14 12:35:34 | 8623 12:23:49 jaya | jaya Bermuda not_home 12:30:26, private_ble 12:33:26; all other residents not_home since 11:51 | RIGHT |
| 10-14 10:21:18 | 8622 10:10:13 oji_udezue | oji Bermuda not_home 10:16:10 (lag 6 min), 8ce182 10:16:29; jaya trackers `home` throughout (last change 06:20/09:48, none in window); exited_today `unidentified` -> `oji_udezue` at 10:21:10 | RIGHT |
| 10-13 12:14:17 | 8603 12:03:27 oji_udezue | oji AND jaya both departed: privates not_home 12:09:10 (same second), jaya Bermuda 12:10:05, oji Bermuda 12:10:10; one crossing row, first edge claims it | UNVERIFIABLE (joint departure) |
| 10-13 00:33:37 | 8599 00:22:37 oji_udezue | oji Bermuda 00:28:05, jaya Bermuda 00:28:19, privates 00:32:09; one crossing row, first edge claims it | UNVERIFIABLE (joint departure) |

Residuals: (1) joint departures with a single recorded crossing name the first-claiming edge (2 of 5 here; both went to oji). The right-or-wrong cannot be settled from the data; v5.97.1 EXIT-COMULTI named each edge its own slug by design. (2) The v5.103.64 display re-read and organic switch path have no organic observation yet (0 backfills since load); revival trigger = next increment of `ble_exit_backfilled_count`, check `sensor.universal_room_automation_last_person_exit` `person_id` within ~5 min.
