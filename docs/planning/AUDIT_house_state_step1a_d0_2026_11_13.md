# AUDIT: house-state step 1a, D0 probe (2026-11-13)

Read-only. Run Fri 2026-11-13 09:37-09:45 CST (15:37-15:45 UTC) by ura-prober. Plan: `PLANNING_house_state_axes_step1.md` rev 3 §A4 D0 (planner worktree). Build under test: `.claude/worktrees/superbuilder-house-state-1a` (HEAD 1c602a1b). Nothing was changed on HA; no Frigate login. The plan asks for the report appended to the audit as §6 "D0 for step 1a"; this is a standalone file, the orchestrator can fold it in.

## Verdict: GO for `EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT=True` and the 300 s window (with caveats), GO for D2 rate

| Gate | Result | Source |
|---|---|---|
| P1(a) added pages per week (limit 3) | **0 measured** in the only window with ground truth (7.2 d, 2 ARRIVING alert-times). 30-day worst case if no alert had resident evidence: 15 MEDIUM / 4.3 wk = **3.5/wk** (over 3). 30-day proxy estimate: **5 of 15 lack in-house evidence = 1.2/wk**. | below |
| P2 counted arrivals >= 3/day | **15.5/day** (112 in 7.23 d), 0 uncounted, 114 departures | below |
| P4 window | 3 lag samples (< 5) -> 300 s default stands | below |
| Lock pages added by `_episode_saw_empty` | **0** measured; the garage lockout kill switch is OFF so the page paths cannot fire today | below |

Caveat on "GO": the plan's number is only truly measured over 7 days; the 30-day figure cannot be resolved because resident geofence history is not retained beyond the recorder window (see Data limits). The 3.5/wk worst case is above the gate; the proxy puts it at 1.2/wk. Per plan text, above 3 would be an operator decision, and the added pages are CRITICAL-at-AWAY-equivalent alerts during body-only ARRIVING.

## Data and method

- Alerts: URA DB `notification_log`, `hazard_type='exterior_person'`, one `message='[audit]'` row per alert (the other rows are per-channel fan-out). 1372 alerts, 2026-10-14 14:49 UTC to 2026-11-13 14:56 UTC (30.0 d). All times UTC unless noted (CDT = UTC-5).
- House state at alert: `house_state_log` (8639 rows; timestamps are naive UTC, matched against alert times) for 30 d; recorder `sensor.ura_presence_coordinator_presence_house_state` for the recorder window. The two agree on 237 of 241 alerts in the window (4 differ by the ~30 s sensor sampling lag, e.g. 11-12 01:12:04 reads ARRIVING in the log, away in the recorder; ARRIVING began 01:12:00 in the log, 01:12:16 in the recorder).
- Residents: recorder `person.oji_udezue/ezinne/jaya/ziri` (raw state; trust-level BLE overrule not reconstructable). Recorder window 2026-11-06 10:12 UTC to 2026-11-13 15:39 UTC = 7.23 d. `person.wall_kiosk` is `unknown` only and excluded.
- Boot windows: 24 `recorder_runs` starts in the window (600 s each).

## P1: exterior-person alerts

Logged severity x house state, 30 d (audit rows):

| state | CRITICAL | HIGH | MEDIUM | LOW |
|---|---|---|---|---|
| away | 341 | | 9 | |
| sleep | 87 | | 3 | 1 |
| home_day | 10 | 779 | | 7 |
| home_evening | 1 | 94 | | |
| home_night | 18 | | | 1 |
| arriving | 3 | | 15 | |
| waking | 1 | | | |
| guest | | | 2 | |

(Logged ARRIVING CRITICAL x3 and AWAY MEDIUM x9 show downstream/other-path severities differ from the plain resolver; mismatch with the logged severity is not decomposable without camera class/track class, which `notification_log` does not store.)

### P1(a): pages ADDED by the ARRIVING arm (MEDIUM -> CRITICAL)

The arm only changes alerts whose live house state is ARRIVING AND that have no resident home AND no counted non-stale non-boot resident arrival within 300 s (`perimeter_alert.py` `_severity_for_current_house_state`, build worktree).

- 18 alerts sat in ARRIVING over 30 d (4.2/wk): 15 MEDIUM, 3 CRITICAL. Only the 15 MEDIUM can rise.
- Measured over the recorder window (7.2 d), by raw person state, at the two alert-times logged ARRIVING+MEDIUM (11-10 00:22:45, 11-12 01:12:04):
  - 11-10 00:22:45: ezinne and jaya home -> evidence, stays MEDIUM.
  - 11-12 01:12:04: ezinne home (since 01:11:36) and jaya home (since 01:10:55), both counted arrivals 29 s and 69 s earlier -> evidence, stays MEDIUM.
  - **Added = 0.** (The recorder-ARRIVING 11-09 14:44 pair logged HIGH, ezinne home, lag 113 s; not an ARRIVING MEDIUM path.)
- 30 d, 15 MEDIUM, resident geofence history only exists for the last 7 d. Proxy for the 13 older alerts: BLE `person_visits` open within 2 h of the alert (in-house indicator, noisy): no open visit for 10-15 15:25, 10-16 21:29, 10-17 20:38, 10-18 19:50 (4 alerts; the 10-16 15:45 and 10-17 00:12 CRITICAL were not MEDIUM). Plus 11-12 01:12 has no open visit but raw geofence showed residents home. So proxy "added" = 4 older + 0 = 4 of 15 plus uncertain; I count 5 including 11-12 under the visit-only proxy (visit-only proxy is wrong for 11-12 because geofence is available), so **4-5 candidates / 4.3 wk = 0.9-1.2 per week**. Worst case with zero resident evidence 15/4.3 = 3.5/wk.
- Pattern: ARRIVING lasts about 30-60 s after `census_update` (lag in state 1-58 s); alerts in that window typically come from the g5_bullet / rear_ptz perimeter cameras while residents are already inside or just arrived (egress `entry` events follow within ~1 min on 8 of 18).

### P1(b): pages REMOVED if `EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY` were True (raw state approximation, recorder window 7.2 d)

| state | logged | raw residents home | alerts |
|---|---|---|---|
| home_day | HIGH | >=1 | 161 |
| home_day | HIGH | 0 | 2 |
| home_evening | HIGH | >=1 | 12 |
| home_night / home_day | CRITICAL / LOW | >=1 | 1 + 4 + 1 (not lowered by persons_home: CRITICAL rows are away/sleep-class overrides) |
| guest | none in the window | | 0 |

Up to 173 HIGH pages (about 24/day) would fall to LOW/MEDIUM depending on camera class and track class. This is the Q4 evidence; the switch ships False regardless.

## P2: producer replay (7.23 d, cold start, `counted_return` / `update_last_real`, min_away 900 s, 600 s boot window)

- Counted arrivals **112** (15.5/day): oji 79, ezinne 17, jaya 9, ziri 7. Uncounted (unknown/unavailable -> home that fails `really_away`): **0**. Departures 114 (15.8/day).
- `source_stale` count: not computable from recorder history (needs the GPS source `last_changed` pair); unknown.
- Plan text said ~10/day; measured is higher (oji alone 11/day), so D2's `>= 3/day` gate passes with margin. Note oji flaps: 722 `not_home` rows over 7.2 d.

## P4: window

ARRIVING alerts with a prior counted resident arrival: lags 59 s, 113 s, 113 s (3 samples; < 5 so 300 s stays). Not enough to tune.

## Lock pages added by `_episode_saw_empty`

Paths (build, `security_lock_regime.py`): `_uncounted_return_pages` (1477), `_boot_gap_return_page` (1160, call 1142); both require `kill_switch_on()`, `reason != NONE`, a lockout still locked.

- `switch.ura_security_coordinator_garage_lockout` is **off** in every one of its 26 recorder rows (last 2026-11-13 14:48:48 UTC; 5 `unavailable` rows 11-11).
- Both lockout entities (`lock.ratgdov25i_dbfe2a_lock_remotes`, `lock.konnected_f0f5bd523b00_lock`; config entry `security_lockout_entities`) were never `locked` in 7.2 d: 24 `unlocked` + 24 `unavailable` rows each.
- Uncounted returns (the `_uncounted_return_pages` input): 0 in 7.2 d (P2).
- Boot rechecks: 24 restarts in 7.2 d, none with a locked lockout.
- **Added pages: 0 measured, structurally 0 while the switch is off.** If the operator arms the lockout, the rate is unmeasurable from existing history (no engaged episodes); the 24 restarts/7 d make the boot-gap arm the one to watch: each restart with an engaged, empty-seen episode and a resident home could page.

## Falsification attempted

- "ARRIVING alerts without resident evidence exist" could be disproved by any resident `home` at alert time; checked via recorder for the two ARRIVING MEDIUM alerts in the window (both falsified, evidence present).
- Log vs recorder house-state disagreement (4/241) could change which alerts are ARRIVING; the 11-12 01:12 alert is the one instance and it keeps evidence either way.
- Lock-page claim would be disproved by any `locked` row or switch `on` row; none exist (SQL: lockout states `unavailable|24`, `unlocked|24` each; switch `off|26`, `unavailable|5`).

## Data limits (unknown, not estimated)

- Raw person geofence history beyond 2026-11-06 10:12 UTC is purged; `person_presence_snapshots` only records state-change `away`-style rows (last row 2026-11-13 09:34, `method='person_state'`), so it was not usable. The 13 older ARRIVING alerts have no resident ground truth.
- Trust-level (BLE overrule) and phone-left-behind cuts are not in the recorder; raw state only.
- Camera class and track class are not stored in `notification_log`; production-recomputed severity (plan P1 column) was not produced, only logged severity.
- `anomaly_log` has no perimeter / exterior metric rows (query `metric_name like '%perim%'/'%exterior%'` returned nothing); alerts were taken from `notification_log` only.

## Files

- Scripts (scratchpad, read-only, not committed): `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/d0.py`, `d1.py`, `d2.py`, `d4.py`, `d5.py`, `d6.py`
- Plan D0: `/Users/okosisi/Code/universal-room-automation/.claude/worktrees/planner-house-state-step1/docs/planning/PLANNING_house_state_axes_step1.md` lines 313-340
