# AUDIT: house_state_log "missing AWAY rows" before ARRIVING

Card: HOUSE-STATE-LOG-MISSING-AWAY-ROWS-1 (`docs/planning/kanban.data.yaml:18639`, Tier 2). Read-only probe by ura-prober, 2026-11-13.
No code, config or HA state changed. Times are UTC unless marked (host `date` reports CST, UTC-6, not CDT).
Read for context: AUDIT_house_state_first_principles_2026_11_13.md section 2 (opening sections), presence.py, house_state.py, database.py.
The PRESENCE state-of-play doc was NOT re-read in full for this probe (the question is a log-integrity question, not a presence-logic one); no ledger claim is asserted here.

## 0. Answer

1. **The "missing AWAY rows" are not a writer skip.** The machine was in AWAY, but AWAY was entered silently, without ever being dispatched/logged. Every one of the 553 rows has `previous_state='away'` (SQL below), so the engine believed it was in AWAY; the log's previous row is a different state in 552 cases (the 553rd is the first row in the table, 2026-03-12T05:20:40, no previous row).
2. **Most probable mechanism (proven in code, partly measured): the machine starts in AWAY by default after every process/manager construction, and that initial AWAY is never logged.** `HouseStateMachine.__init__(initial_state=AWAY)` (`house_state.py:153,157`), constructed with no restore in `manager.py:225`. Before v5.103.27 (deployed 2026-09-29 22:39 CDT, commit `f69adaea`) there was no restore at all. The first inference tick after boot then proposes AWAY->ARRIVING (people are home), that transition is logged with `previous_state='away'`, but the AWAY that preceded it never was.
3. **Measured support is partial, not complete.** Rows within 15 min after a >=300 s `energy_snapshots` outage: 118 of 544 gap rows (21.7%) vs 55 of 2089 normal AWAY->ARRIVING rows (2.6%); within 60 min: 195 (35.8%) vs 169 (8.1%). That is an 8x enrichment but leaves ~64% of gap rows not tied to a detectable outage. The remainder is **unknown**: a manager re-construction without a process restart (coordinator-manager reload re-runs `manager.py:225`) is the untested candidate. No reload log exists for that era.
4. **The defect is already fixed going forward.** Gap rate: 75 in Sep 2026, 1 in Oct (10-03), 0 in Nov (130 rows). Over the recorder window 11-05..11-13 there were 23 recorder runs (restarts) and **zero** gap rows. The restore + boot-reconcile (v5.103.27, `house_state.py:35` max-stale 1800 s, `presence.py:2600-2680`) closes the common case.
5. **Impact on counts:** `AWAY entries` (`exclude_same_previous`, `presence.py:~9215`) are not undercounted by "missing AWAY rows" in the sense of lost real departures. The 553 rows are mostly restart artifacts (a fake AWAY->ARRIVING with no real AWAY), so ARRIVING counts (2,642) are **overcounted** by up to ~21% pre-10-03, and real-arrival rate figures built on them inherit that. Post-10-03 counts are clean.

## 1. Writer inventory (producer check)

| Item | Evidence |
|---|---|
| Only one writer of the table | `database.py:3050-3070` `log_house_state_change`; only caller `presence.py:9338` inside `_dispatch_house_state_change` (`:9225`). grep over `custom_components` finds no other INSERT. |
| Swallows errors | `database.py:3070-3071` logs `Error logging house state change` and returns; a failed insert is silent in the table. |
| Pre-v5.103.27 call site | inline on every accepted `transition()` in `_run_inference`, unconditional (`git show 326cb0d7^:presence.py` lines 6700-6713). No dedup/debounce/gate. |
| Current call site | `_dispatch_house_state_change` skips the log (returns early) when `_boot_settle_done` is False (`presence.py:~9243-9251`) or `observation_mode` (`:9252-9258`). The AWAY-entry counter is deliberately placed after these gates so it tracks written rows. |
| Table schema | `database.py:1525-1535`; row carries `previous_state` (the engine's belief), written from `current_state.value`. |
| No dedup / debounce | none exists in the writer; hysteresis lives in the state machine only (`house_state.py:129-139`). |

## 2. Classification of the 553 rows

All SQL against the live URA DB (`ssh ha sqlite3 -readonly`; the Samba-mount copy would not open read-only through sqlite3, so the SSH path was used). Total rows 8,636 (2026-03-12..2026-11-13); ARRIVING 2,642; AWAY 2,089.

| Class (brief) | Count | Evidence |
|---|---|---|
| Direct X->ARRIVING (AWAY never entered) | **0** | `previous_state` is `'away'` for all 553. `VALID_TRANSITIONS` lets ARRIVING be reached from AWAY (and VACATION, `house_state.py:73,123`); no row shows a different `previous_state`. |
| AWAY not logged because the writer skipped an accepted transition | **0 observed pre-v5.103.27** (writer unconditional); **cannot be ruled out for boot-settle-gated AWAY post-v5.103.27** (gap rows after that deploy: 2) | pre-deploy code cited above. |
| Silent AWAY entry (machine default / reconstruction) | **552** (all gap rows with a prior row); of which **118 have a >=300 s data outage ending <=15 min before** (restart proxy), 195 within 60 min | q8 below. The other ~357 are consistent with the same mechanism but **unproven**. |
| First row of table | 1 | row 2026-03-12T05:20:40, prev row NULL, trigger deferred_retry. |
| Log written from a different path | 0 | single writer (section 1). |

Breakdown of the 553 by previous row state: home_day 157, sleep 134, guest 112, home_evening 81, home_night 39, arriving 29 (an ARRIVING->(silent AWAY)->ARRIVING repeat), none 1. By trigger: deferred_retry 246, occupancy_change 166, census_update 138, guest_room_occupancy 2, geofence_arrive 1. Gap between previous row and the ARRIVING row: <2 min 6, 2-30 min 197, 30 min-12 h 341, >12 h 8.

Nature check: of all chain breaks (previous row state != `previous_state`) in the table there are 562; **552 are "into ARRIVING"**, 1 into AWAY, 9 into other states (April, mostly GUEST/WAKING). The silent-state phenomenon is overwhelmingly specific to AWAY, which is the machine's constructor default; it is not a general logging hole.

Timeline of gap rows per month (Mar..Nov): 62, 104, 108, 81, 57, 65, 75, 1, 0. Last two after the v5.103.27 deploy (2026-09-30T03:39Z): 2026-09-30T12:51:15 (prev row guest, trigger guest_room_occupancy) and 2026-10-03T21:59:55 (prev row home_day at 11:01, 10.9 h earlier, trigger deferred_retry). The second fits the 1800 s max-stale rule (`house_state.py:35`): a long outage makes the restore stale and falls back to the silent default. The first was not individually diagnosed (unknown).

## 3. Recorder cross-check (window 2026-11-05 04:12 to 2026-11-13, `sensor.ura_coordinator_manager_house_state`, 22,894 state rows)

- Recorder state edges between known values since 11-05 10:00 UTC: **84**. Of these **0** have no matching `house_state_log` row (same new state, +-60 s; the log row precedes the sensor edge by 11-20 s because the sensor is sampled every ~30 s: example 11-06 12:00:12 log vs 12:00:23 recorder).
- Recorder edges into ARRIVING: 16, all from `away`; the log has all 16 preceded by an AWAY row. Gap rows in this window: 0.
- 14 log rows (11-05 12:00 .. 11-06 04:44) have no recorder edge. They form a contiguous, self-consistent chain (each `previous_state` equals the previous row). They predate the first recorder edges for this entity in the window; cause of the missing recorder edges was not diagnosed (recorder purge/exclusion unknown).
- So for the only window with an independent record, the log and the recorder agree fully. The recorder (retention ~8 days) cannot test the Mar-Oct gaps; that era was tested only by the outage proxy above.

## 4. Falsification

- Claim: "gap rows are restart/reconstruction artifacts, not a writer skip." Would be disproved by (a) accepted AWAY transitions pre-deploy not appearing in the log: not observed, the writer was unconditional; (b) gap rows continuing after the restore fix despite many restarts: not observed (0 in Nov with 23 recorder runs, 1 in Oct); (c) gap rate in normal operation independent of outages: not true (2.6% control vs 21.7% within 15 min).
- Claim is NOT fully proven: 64% of gap rows have no detectable outage in `energy_snapshots` (cadence ~9 s, gaps >=300 s counted; 607 such gaps since 03-12, so the proxy is noisy and could over- and under-count). A manager reload (re-runs `manager.py:225`) is the leading unproven alternative. To prove it the card needs per-boot/per-reload markers for the Mar-Sep period, which do not exist in the DB (`ura_activity_log` only starts 2026-10-14).

## 5. Fix recommendation

1. **Do not build a log-writer fix.** The writer is correct; the post-v5.103.27 behaviour already cures the main source (0 gaps in 41 days). Close the card as "explained, fixed by v5.103.27", with the residual below.
2. **Repair the counts, not the table (cheap, read-side):** for any rate computed from `house_state_log` before 2026-10-01, treat an ARRIVING row whose previous *row* is not AWAY as a **restart artifact, not an arrival** (exclude, or synthesise the missing AWAY edge). Use `previous_state` only for AWAY-entry counts, and never infer "real arrival" from the 2,642 ARRIVING total. Anything in `AUDIT_arriving_on_body_evidence` or the first-principles audit that used raw ARRIVING counts for pre-October data should note ~21% are artifacts (this partially corrects the "6.4% real arrivals" denominator; the ratio of real arrivals to non-artifact ARRIVING edges is higher than stated).
3. **Residual (small, Tier 1):** restore falls back to a silent AWAY when the stored state is older than 1800 s (the 10-03 row). A cold-boot or stale-restore AWAY should be logged with trigger `boot_default` (or the first ARRIVING after it should carry that trigger) so the log is self-consistent. Wire-in anchor: the constructor default at `house_state.py:157`, with the stale-reject branch at `manager.py:699-715`. Add the zero-fire/anomaly trip-wire per CLAUDE.md: any `house_state_log` row whose `previous_state` != previous row state should raise an anomaly (the recurrence of this gap class would otherwise be silent).
4. Optional: make `log_house_state_change` surface insert failures (`database.py:3070` currently only logs) and count them, since a swallowed write failure is indistinguishable from this class in the table.

## 6. Queries used (reproducible)

- `lag(state) over (order by timestamp,rowid)` per row; ARRIVING rows where lag != 'away': 553 of 2,642; `previous_state='away'` for all.
- Outage proxy: `energy_snapshots` consecutive-row gaps >=300 s (607 since 2026-03-12), join to ARRIVING rows with end-of-outage <= row time within 15/60 min: gap rows 118/195 of 544, control (previous row = AWAY) 55/2089 and 169/2089. (Rows before 2026-03-13 excluded, 544 = 553 minus 9 early rows.)
- Recorder cross-check: attach URA DB, edge-compare `states` for `sensor.ura_coordinator_manager_house_state` with `house_state_log`, +-60 s.
- Scratch SQL files: `/Users/okosisi/Code/universal-room-automation/.claude/scratch/q1.sql` .. `q10.sql` (untracked).
