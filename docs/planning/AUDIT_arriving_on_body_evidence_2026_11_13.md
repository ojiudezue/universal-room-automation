# AUDIT: how often AWAY -> ARRIVING fired on non-resident evidence, and what it actuated

Card: LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1 (`docs/planning/kanban.data.yaml:34759`). Read-only probe, 2026-11-13 00:24 CST.
Prepared by ura-prober. I read `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (796 lines) and
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (1017 lines) completely before querying.

All times CST/CDT unless marked `Z` (UTC). `house_state_log` timestamps are naive UTC.

## 1. Verdict (lead)

1. **Camera-only ARRIVING has released access zero times.** Every access actuator on this path was off for the whole
   time the code existed. Garage lockout switch `off` in every recorder row, `lock.ratgdov25i_dbfe2a_lock_remotes`
   and `lock.konnected_f0f5bd523b00_lock` never `locked`, armed state `disarmed` in every row, `security_auto_follow`
   `False` in the live entry, and 0 rows of any `lock_regime_*` / `auto_follow` in `decision_log` (8.5 months) or
   `ura_activity_log`. The hazard is real in code but dormant; it arms the day the operator turns the lockout on.
2. **The card's premise is half right.** Of 2,642 AWAY -> ARRIVING edges since 2026-03-12, only 95 were driven by
   the camera/census leg with no resident evidence. **1,810 (68.5%) fired with `census_count == 0`, i.e. on zone
   (room-sensor) occupancy alone**, which `presence.py:1347` ORs with the census (`has_people = census_count > 0 or
   any_zone_occupied`). Any fix scoped to "camera bodies" misses the dominant driver.
3. **Real arrivals are a small minority of ARRIVING edges** (168 of 2,642 = 6.4%; 17 of 19 in the recorder window).
   Most ARRIVING edges (1,285 = 48.6%) are the house recovering from a false AWAY while a resident was home.
4. **A resident's phone edge almost always precedes ARRIVING**: in the 17 precisely measurable real arrivals the
   nearest tracker edge led ARRIVING by a median 35 s (16 of 17 led; 1 trailed by 45 s). The existing person-arrival
   release path (`security_lock_regime.py` `_process_person_edge` S1) already fires on that edge, so the
   house-state release at `:864` is redundant for real arrivals and is the only path that fires for the non-real ones.
5. **Recommended fix:** stop treating a bare house-state ARRIVING edge as a lockout release (shape in section 7). Cost:
   one of 17 recent real arrivals gets its release 45-55 s later via the person path instead of the house-state path.

## 2. Method and data sources

| Item | Source |
|---|---|
| ARRIVING edges | URA DB `house_state_log` (8,636 rows, 2026-03-12 -> 2026-11-13; `ssh ha sqlite3 -readonly`); 2,642 rows `state='arriving'`, all with `previous_state='away'` |
| Per-edge evidence | `decision_log` `coordinator_id='presence' AND decision_type='state_transition'` context (`census_count`, zone modes); `census_snapshots` zone `house` rows (identified / unidentified / frigate / unifi), nearest within +/-100 s (exists from 2026-08-14) |
| Resident edge truth, 2026-11-05 10:12Z -> now | HA recorder `/config/home-assistant_v2.db` (`states`, `state_attributes`): `person.{oji_udezue,ezinne,ziri,jaya}` `not_home -> home` with `source` tracker; `private_ble_device_*` / `*_bermuda_tracker` = BLE, everything else = GPS/app. Recorder holds only 8 days (`min(last_updated_ts)` = 2026-11-05 10:12:00Z) |
| Resident edge truth, 2026-03-12 -> 2026-11-05 | `person_presence_snapshots` (15-minute cadence, merged from live DB + `.bak-pre-drop-orphan-2026-05-15` + `.prevacuum.bak` + `ura_db_pre_energy_backfill_20261024.db` opened `?immutable=1`). Coverage gap 2026-06-19 20:19 -> 2026-07-27 00:10 (no snapshots anywhere) |
| Actuation | recorder `states` for the lockout switch, away-lock switch, lock entities, `sensor.ura_security_coordinator_security_armed_state`; `decision_log`; `ura_activity_log`; live attributes `lock_regime_*` on the armed-state sensor (read via `/api/states`, token not printed) |
| Code | `presence.py:1347-1369`, `security_lock_regime.py:836-870, 1566-1600, 1674-1697`, `security.py:192, 1387-1455, 1186-1203` |

Classification of each AWAY -> ARRIVING edge E:

- **real_arrival**: a resident (Oji, Ezinne, Ziri, Jaya) `not_home -> home` edge within +/-10 min of E. Recorder window:
  exact. Snapshot window: bracketed by two 15-min snapshots whose interval intersects E +/-10 min (looser than +/-10 min).
- **resident_already_home**: no edge, but a resident was already home at E (the preceding AWAY was false; ARRIVING is the correction).
- **no_resident_evidence** (the card's "camera-only false"): no edge and no resident home. Includes zone-sensor-only edges.
  This is NOT proof of a stranger: see 4.3.
- **unclassifiable**: no snapshot within 30 min (06-19 -> 07-27 gap, early April).

Per-edge CSV of all 2,642 rows (scratchpad, not a repo file):
`/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/arriving_events_all.csv`.

## 3. Counts

### 3.1 All history (2026-03-12 -> 2026-11-13), 2,642 AWAY -> ARRIVING edges

| Class | n | % |
|---|---|---|
| real_arrival | 168 | 6.4 |
| resident_already_home (false AWAY recovering) | 1,285 | 48.6 |
| **no_resident_evidence** | **867** | **32.8** |
| unclassifiable (no snapshot) | 322 | 12.2 |

Flap structure: 902 distinct AWAY episodes (AWAY entered from a non-ARRIVING state); 1,187 of the 2,089 AWAY rows were
entered from ARRIVING (collapse). Edges per episode: 1 -> 602, 2 -> 132, 3 -> 55, 4 -> 28, 5 -> 16, 6+ -> 69.
Episodes whose first edge had no resident evidence and never had one: 210; first edge no-evidence but a later edge real: 6.

### 3.2 Evidence leg at the edge x class

`census_count` = `decision_log` context at the edge. Camera-body split uses `census_snapshots` (available from 2026-08-14 only).

| Evidence leg | real | already_home | no_resident_evidence | unclass. | total |
|---|---|---|---|---|---|
| zone occupancy only (`census_count==0`) | 98 | 697 | **772** | 243 | 1,810 |
| census>0, a name identified | 25 | 93 | 8 | 0 | 126 |
| census>0, camera body unnamed (unid/frigate/unifi >0, ident 0) | 3 | 47 | **40** | 0 | 90 |
| census>0, other (ident 0, no body in snapshot) | 7 | 31 | 21 | 0 | 59 |
| census>0, pre-08-14 (not splittable) | 32 | 389 | 23 | 72 | 516 |
| context missing | 3 | 28 | 3 | 7 | 41 |
| **total** | 168 | 1,285 | 867 | 322 | 2,642 |

Zone-only no-resident edges by zone (`zones` mode != away): Back Hallway 502, Entertainment 133, Master Suite 73, Upstairs 50, Outside 30.
By month, zone-only no-resident: 03: 83, 04: 6, 05: 126, 06: 7, 07: 316, 08: 230, 09: 0, 10: 4, 11: 0 (the July-August bulk is the Back Hallway phantom epoch; near zero since September).
By month, census>0 no-resident: 03: 3, 04: 4, 05: 5, 07: 2, 08: 8, 09: 9, **10: 60**, 11: 1.

Falsification of "zone-only is real": of 27 zone-only edges since 08-14 with a nearest census snapshot, 1 had a camera body in the snapshot. So `census_count == 0` with a zone occupied genuinely means no camera body was counted.

### 3.3 Recent windows

| Window | edges | real | already_home | no_resident_evidence |
|---|---|---|---|---|
| since 10-14 | 144 | 23 | 56 | 65 |
| since 10-26 (sleep-mask / BLE-grace era) | 36 | 17 | 16 | 3 |
| since 11-07 (lock-regime code committed, `10da1b98`, 2026-11-07 12:30 CST) | 13 | 11 | 1 | 1 |
| since 11-10 07:04Z (v5.108.1 restart) | 8 | 6 | 1 | 1 |

The 10-14 -> 10-18 cluster (59 of the 60 October camera-leg edges: 10-14: 16, 10-15: 8, 10-16: 31, 10-17: 3, 10-18: 1) falls in
the operator-travel window; every snapshot on 10-16 12:00-18:00Z reads all four residents `away` (24/24 per person). The memory
note says Jaya and a guest were home; the DB cannot confirm that, so the occupant identity is **unknown**. Treat these as an untracked
occupant, not a proven stranger.

### 3.4 What the no-resident ARRIVING edges did next

Of 867: 631 collapsed back to AWAY within ~60 s (`next=away`), 236 advanced to HOME_* (27%).

## 4. Evidence detail

### 4.1 The ARRIVING branch (code)

`presence.py:1347-1369`: `has_people = census_count > 0 or any_zone_occupied`; `if current_state == HouseState.AWAY: ... return HouseState.ARRIVING`.
No distinction between a resident edge, a named face, an unnamed camera body, or a room sensor. Re-arm cooldown (`presence.py:8167-8290`,
`ARRIVING_REARM_COOLDOWN_S`) only damps repeats of outdoor-only attempts.

### 4.2 Recorder-window edges (2026-11-05 10:12Z -> now), exact edge truth, 19 edges

`id` = `house_state_log.id`. `Evidence` = census_count / (ident, unident, frigate, unifi) from the nearest snapshot. `Edge` = resident
`not_home -> home` and its offset from ARRIVING in seconds (negative = edge first). `Act 5m` = lock/arm state changes within +5 min of E
in the recorder (lockout switch, remotes locks, front/garage/master locks, armed state).

| id | CST | AWAY from | trigger | Evidence | Class | Resident edge (lag s) | Next | Act 5m |
|---|---|---|---|---|---|---|---|---|
| 8545 | 11-05 08:31:58 | home_day | periodic | cc1, Upstairs; (1,0,0,0) | real | Oji GPS (-65) | home_day 60s | none |
| 8549 | 11-05 18:26:19 | home_evening | census_update | cc1; (1,0,0,0) | real | Oji GPS (-101) | home_evening | remotes `unlocked` +109 s (boot/unavailable flicker, switch off) |
| 8553 | 11-05 22:41:03 | home_night | census_update | cc1; (1,0,0,0) | real | Oji GPS (-34), Jaya BLE (-16) | home_night | none |
| 8559 | 11-06 09:03:16 | home_day | periodic | cc1; (1,0,0,0) | real | Oji GPS (-147), Oji BLE (-121) | home_day | none |
| 8563 | 11-06 22:06:34 | home_evening | census_update | cc3; (3,0,0,0) | real | Oji GPS (-33), Jaya BLE (-25), Ezinne GPS (-19) | home_night | none |
| 8569 | 11-07 10:34:05 | home_day | census_update | cc3; (3,0,0,0) | real | Ezinne GPS (-40), Jaya BLE (-37), Ziri GPS (-35), Oji GPS (-374) | home_day | none |
| 8572 | 11-07 17:40:34 | home_day | census_update | cc1; (1,0,0,0) | real | Ziri GPS (-4) | home_day | none |
| 8576 | 11-07 18:12:03 | home_evening | periodic | cc0, Upstairs; (0,0,0,0) | real | Ezinne GPS (-35), Oji GPS (-35) | home_evening | none |
| 8583 | 11-08 14:00:04 | home_day | periodic | cc2; (2,0,0,0) | real | Ezinne GPS (-73), Oji BLE (-73) | home_day | none |
| 8591 | 11-09 08:42:47 | home_day | census_update | cc1; (1,0,0,0) | real | Ezinne GPS (-30) | home_day | none |
| 8594 | 11-09 18:22:18 | home_day | census_update | cc2; (0,0,0,0) | real | Ezinne GPS (-53), Jaya BLE (-33) | home_evening | none |
| 8602 | 11-10 19:25:07 | home_evening | census_update | cc2; (0,0,0,0) | real | Ezinne GPS (-40), Jaya BLE (-29) | home_evening | none |
| 8609 | 11-11 08:26:19 | home_day | occupancy_change | cc1, Back Hall+Upstairs; (1,0,0,0) | real | Ezinne GPS (-88) | home_day | none |
| 8612 | 11-11 17:33:26 | home_day | periodic | cc1; (1,0,0,0) | real | Ezinne GPS (-65) | home_day | none |
| 8616 | 11-11 19:12:00 | home_evening | census_update | cc2; (2,0,0,0) | real | Ezinne GPS (-68), Jaya BLE (-65) | home_evening | none |
| **8623** | **11-12 07:35:40** | home_day | deferred_retry | cc1, Upstairs; **(0,1,1,0)** | **no_resident_evidence** | none; Ezinne and Jaya went `not_home` 07:34:02 (13:34:02Z), Oji `not_home` 07:36:38 | home_day 61s | none |
| 8626 | 11-12 10:56:57 | home_day | census_update | cc1, Upstairs; (0,1,1,0) | already_home | Ezinne home (Living Room BLE 10:52) | home_day | none |
| 8629 | 11-12 13:38:34 | home_day | census_update | cc1; (0,0,0,0) | real | Ezinne GPS (-45) | home_day | none |
| 8632 | 11-12 16:43:07 | home_day | census_update | cc2; **(0,1,1,0)** | real | Ezinne GPS (+45), Jaya BLE (+55) | home_day | none |

Two edges worth reading:

- **8623 is the one camera-only ARRIVING in the exact window.** Both residents present left at 07:34:02; the house went AWAY
  at 07:35:10 and ARRIVING 30 s later on one unnamed body still in frame (`census_snapshots` 13:35:55Z `(0,1,1,0)`, no `identified_persons`).
  It was the leaving residents' own tail, not an arrival, and the house then moved to HOME_DAY 61 s later. Nothing was actuated because every access arm was off.
- **8632 is camera-first but real:** ARRIVING led the Ezinne/Jaya tracker edges by 45/55 s.

Lag across the 17 real edges (exact): `[-121,-101,-88,-73,-65,-65,-65,-45,-35,-35,-33,-30,-29,-19,-16,-4,+45]`, median -35 s.
Source mix: BLE+GPS 9, GPS only 8. GPS alone covered every one.

Actuation in the 5 minutes after any of the 19: no lockout release (switch off), no armed-state change (always `disarmed`), no door-lock unlock
attributable to URA. The only lock change is 8549's remotes `unlocked` at +109 s, which is the boot/availability flicker seen at
every URA restart (`unavailable -> unlocked`, e.g. 11-05 21:02, 11-07 17:33, 11-08 00:23) and not an ARRIVING action (switch off, no decision row).
A master-bedroom lock `unlocking` at 11-06 04:46:54Z (22:46 CST on 11-05) arrived 5 min 43 s after the 04:41:11Z ARRIVING (outside 5 min, and the lock-regime code did not exist yet on 11-06).

### 4.3 What "no_resident_evidence" is not

The classifier cannot see an untracked occupant (a guest, a resident with no phone state). The 10-14 -> 10-18 cluster and 8623 show
the failure on both sides: a real occupant (guest/untracked) and a departing resident's tail both land in this class. The actuation
policy question is therefore identity-or-independent-edge, not "is a body a stranger".

## 5. The review-D repro shape (lockout engaged in SLEEP, SLEEP -> AWAY, interior body -> ARRIVING -> release)

Code path (verified): the lockout engages on `sleep` (`security_lock_regime.py:866-867`); `away` is `("none", None)` so the reason
persists; `arriving` returns `"release"` unconditionally (`:864`); `_release` runs when the garage switch is on and SC alive (`:1566-1600`);
because the trigger is `house_state:*`, `_after_release` (`:1676-1686`) clears the reason, cancels re-engage and the backstop: the episode is over,
**no re-engage** (a person-path release instead schedules `_schedule_reengage`, `:1694-1697`).

History, SLEEP -> AWAY entries (46 total, 45 inside the 22:00-06:00 local window) and the first ARRIVING after each:

| Cluster | n | evidence leg | class of the following ARRIVING |
|---|---|---|---|
| 2026-03-31 23:28 -> 04-01 05:43 CDT (one night) | 14 | zone only (1 census>0 unsplit) | unclassifiable (no snapshot) |
| 2026-04-02 00:01 -> 02:49 CDT (one night) | 9 | zone only | already_home: all four residents home (sleep-mask false AWAY) |
| 06-19 22:10 -> 22:58, 06-26 23:23/23:39, 07-14 22:12 -> 22:40 | 9 | zone only | unclassifiable (06-19 -> 07-27 snapshot gap) |
| 07-27 02:17 -> 07-28 03:38 | 7 | zone only (Back Hallway epoch) | no_resident_evidence |
| 08-27 22:25, 09-12 23:26, 09-14 23:12, 10-01 09:57, 10-31 23:21 | 5 | census>0 named / other | already_home |
| roll-up (46) | | | already_home 14, no_resident_evidence 7, unclassifiable 25; real_arrival 0 |

- Zero of the 46 were a real arrival; **none had an unnamed camera-body leg as the driver** (the camera-body class is 0 for sleep-originated chains).
  The repro as written (an interior body) is reachable in code but the history shows the driver was zone occupancy or residents asleep with a false AWAY.
- The last SLEEP -> AWAY entry was 2026-10-31 23:21 CDT; zero since the sleep-mask D1 fix went live (v5.108.1, 2026-11-10 01:04 CST). Consistent with the doc's own claim; I did not re-verify the fix at code level.
- GUEST -> AWAY: 42 entries, **0 inside the sleep window** (lockout engages on GUEST only inside it, `:870`), so the guest-night variant never arose.
- At the time of every one of these 46, the lockout code did not exist (first commit 2026-11-07), so none released anything.

## 6. Forward trace: what ARRIVING can actuate

| Consumer | file:line | Gate today | Fired on camera/zone-only ARRIVING? |
|---|---|---|---|
| Garage lockout release | `security_lock_regime.py:864` -> `_release` `:1566` | `kill_switch_on()` (live `switch.ura_security_coordinator_garage_lockout` = off) | **0** (switch off; `lock_regime_garage_lockout_last_action` = `{}`) |
| Away lock | not on this path; only `SIGNAL_PERSON_ARRIVING` (`:1040-1052`) | `switch...away_lock` off | n/a |
| Door-lock unlock | none on house state; `lock.unlock` only at `security_lock_regime.py:778/1704/2437` (person/proximity/hazard/teardown) and `security.py:2335` (hazard) | n/a | 0 |
| Security auto-disarm | `security.py:192` map, `:1387-1455` | `_auto_follow_house_state` = `False` (live entry `security_auto_follow: False`; board `:301`) | **0** (armed state `disarmed` in every recorder row; 0 `auto_follow` rows in `decision_log`) |
| HVAC | `hvac.py:2853-2856` skips preset changes in ARRIVING | n/a (not an access action) | n/a |

Fire check: ARRIVING itself fired 2,642 times; the lock-regime release branch fired 0 times (switch off); auto-follow disarm 0 times.
A trip-wire for "release on non-corroborated ARRIVING" does not exist yet.

Caveat: the lockout code first appears in the recorder as an entity on 2026-11-08 00:23Z (switch `off`). The two ARRIVING edges before that
(8572 and earlier) predate the entity. I did not find any evidence the switch has ever been `on`, but the recorder cannot prove a negative
before 11-05; the DB-side evidence (no `lock_regime_*` rows) is the stronger statement.

## 7. Recommended fix shape (Tier 3, per the card; marginal-benefit view)

Value is latent-only today; the cheapest change that removes the exposure beats a corroboration scheme.

1. **Simplest, recommended: a bare house-state `arriving` edge no longer releases the lockout.** Remove the `if new == "arriving": return "release"`
   branch at `security_lock_regime.py:864`, and keep WAKING / HOME_* / backstop / resident person edges / proximity / hazard as the release paths.
   Why it costs almost nothing: in 16 of 17 exact real arrivals the resident tracker edge preceded ARRIVING by 4-147 s (median 35 s) and the
   person path (`_process_person_edge` S1, with the 15-min really-away rule and the 5 s suspicious-arrival hold) already released; the 17th (8632)
   would release 45 s later at its tracker edge. It also gains the re-engage behaviour (`_schedule_reengage`) that the house-state release loses.
2. **Do not stop at `:864`.** The `new in _HOME_STATES` branch (`:858-860`) also releases when `reason != NONE`, and 236 of 867 no-resident
   ARRIVING edges advanced to HOME_* 60 s later. If the SLEEP lockout is still engaged (it will be, since step 1 no longer clears it) a camera-only
   ARRIVING -> HOME_* chain would release one tick later. Gate that branch on "previous house state was not ARRIVING from AWAY"
   (or on a stamped resident arrival edge within `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S`, reusing `arrival_edges.py`). Keep WAKING and manual-override HOME_* releases.
3. **Do not add camera-body-specific logic.** 68.5% of ARRIVING edges are zone-occupancy-only; a "camera body" predicate would miss them.
   The policy belongs in the consumer (lock regime), not the producer: ARRIVING stays as is for HVAC/NM/lighting.
4. **Trade-off to state to the operator:** an arrival with no tracker edge (phoneless guest, dead phone) no longer unlocks the lockout via ARRIVING; it
   waits for WAKING / the morning backstop (`number.ura_garage_lockout_morning_backstop`, live 60) or a manual unlock. The operator's constraint
   ("feeling locked out is a nasty feeling") applies, so keep a path: the existing proximity release (`security_lockout_distance_sensors`,
   `number.ura_garage_lockout_approach_radius` 1500) and the manual unlock remain.
5. **Auto-disarm (`security.py:192`)** is a separate switch (`security_auto_follow`, off). If it is ever turned on, ARRIVING -> DISARMED has the
   same exposure; it should require the same corroboration or be left off. No evidence it has ever fired.
6. **Trip-wire (per the fire-check rule):** one anomaly to NM when a lockout release trigger is `house_state:arriving` with no resident edge stamped in
   the prior 120 s. Zero-fire is the expected steady state.
7. **Parked fancier alternative:** require a named identity or an independent edge for every ARRIVING-driven release (the card's text). Marginal gain over
   option 1 is the 1-in-17 camera-first case; marginal ingredient risk is a new reader on the identity path with 44% egress attach. Revisit only if
   resident-edge lag worsens (e.g. a tracker outage makes ARRIVING the only signal).

Acceptance criteria that discriminate: (a) replay the 10-14 -> 10-18 cluster and 8623 with the lockout on and engaged: zero `lock_regime_release` rows;
(b) replay 8545-8632 real arrivals: each still releases, via `person:*` triggers, within 60 s of ARRIVING; (c) the SLEEP -> AWAY -> ARRIVING fixture
(04-02 shape) leaves the reason `sleep` until WAKING or the backstop.

## 8. Limits and unknowns

- Ground truth before 2026-11-05 is 15-min snapshots; "real" is bracketed, not exact (+/- up to 15 min), and `resident_already_home` uses a snapshot up to 30 min stale. The real/already-home split in that era carries that error.
- 322 edges are unclassifiable (snapshot gap 06-19 -> 07-27; early April).
- `census_snapshots` exists only since 2026-08-14, so the camera-body split cannot be made for the 516 earlier census>0 edges.
- The recorder retains 8 days; lockout/armed state history before 11-05 comes only from the DB and the code's commit date.
- Occupant identity during 10-14 -> 10-18 is unknown (see 3.3).
- I did not run any test or mutate any state; the HA token was used for one `GET /api/states` read.

## 9. Files

- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/presence.py` (1347-1369, 8167-8290)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/security_lock_regime.py` (836-870, 1040-1052, 1566-1600, 1674-1697)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/security.py` (192, 1186-1203, 1387-1455)
- Per-edge CSV: scratchpad path in section 2.
