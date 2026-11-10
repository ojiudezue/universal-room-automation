# AUDIT: guest onset/eviction thresholds, and the HVAC evidence rule for the other house states

**Date:** 2026-11-10 01:10 CST. **Read-only measurement.** Cards: GUEST-MODE-SPLIT-VISITORS-1 (thresholds), HVAC-GUEST-EVIDENCE-RULE-1 (Part 2).
**Read first (completely):** `docs/Coordinator/GUEST_MODE.md`, `docs/planning/PLANNING_guest_mode_split_2026_11.md` (all 1071 lines were not re-read; §0-§5.5 and §6 head were), `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all 726 lines).

## Answer first

**Part 1.** None of the simpler candidates is faster, and none is better, on the October stay.
- First detection is 1 calendar day after arrival (09-28 morning, about 17 h after the first guest-room occupancy at 09-27 12:43) under every candidate except day-only arming.
- Raising the night threshold above 0.25 only costs stay days (0.30: 16/21, 0.40: 13/21, because the same threshold gates the hold).
- Day-only arming has zero false days in the clean period (max day fraction 0.051, vs the 0.10 bar) but 17 false/unlabelled days before the stay and cannot hold the stay (6/21 to 14/21 unless the exit is 7 days).
- A day-fraction drop is NOT a faster eviction signal: October stay days read 0.00-0.05 on 14 of 21 days, so any day-based exit either false-exits mid-stay or is slower than empty nights.
- **Real defect found in the current rule:** the stay's last real day (10-17, GB2 day fraction 0.22, guest-room occupied until 18:52) is dropped. The re-entry-grace stay has n=1, so one empty night ends it (10-16 empty), although day 10-16 read 0.46 and 10-17 read 0.22. A "day veto" (do not exit on empty nights while a day fraction >= 0.10 sits inside the exit window) recovers it: 19/21 stay days, clean period 0/21, no mid-stay false exit.
- **Recommendation:** keep 0.25 / 0.10 / exit 2 nights. Add the day veto to the exit test. Do not adopt (b), (c) or (d). Optional: decouple entry (0.40) from hold (0.25); on this data it removes one unlabelled one-night entry (09-10) and costs nothing.

**Part 2.** The shadow/comparison log does not exist for the non-evidence states, and the evidence rule is not even computed in them (`hvac_zones.py:1634-1650` returns early). The only data are an 8-day recorder window (11-02 to 11-10) plus an occupancy_events proxy. Verdicts: **guest INSUFFICIENT DATA (lean safe by equivalence), home_night INSUFFICIENT DATA, arriving INSUFFICIENT DATA, away INSUFFICIENT DATA (and low value).** Direction is always the same: the evidence rule conditions LESS, never more.

---

## PART 1: guest onset and eviction

### 1.1 Method, and what I used instead of the harness

- `quality/tests/guest_split_harness.py` is a World driver (real `_run_inference`, real gates). It does not replay the DB walk. The replay lives in `quality/tests/test_guest_stay_producer.py` over `fixtures/guest_stay_r5_replay.json`.
- I ported the `_refresh_guest_stay` walk (`presence.py:6133-6330`, read in full) into a pure function and regenerated the per-night and per-day guest-room fractions from the LIVE URA DB (`occupancy_events` + `person_visits`, 12 h episode cap, resident pad 120 s, 22:00-06:00 night, 10:00-22:00 day, same room) on 2026-11-10 01:03 CST through 11-09.
- **Validation of the port (falsifier):** at the production defaults it reproduces the test's expected day list exactly: 08-25..09-01, 09-05..09-07, 09-10, 09-16, 09-28..10-14, 10-16 (`test_guest_stay_producer.py:221-226`). The night fractions equal the plan's §5.2 list (0.72, 0.66, 0.82, ...).
- Scripts (scratchpad): `.../scratchpad/g/fr.py` (fractions), `sim.py` / `sim2.py` (walk + variants), `run3.py`, `gap.py`. Data pull `dump.py` via `ssh ha`.
- "Day active" = the latch is on during that local day (night N evaluated the morning after). Lag = first active day minus 09-27 (arrival; first occupancy 12:43). Exit lag = last active day minus 10-17 (brief's stay end).
- **Caveat the operator named:** the October stay is one stay and not a model one. The guest left often; 10-13 and 10-14 nights read 0; the true departure is unknown (guest-room occupancy continues in short episodes until 10-18 12:38 and a 6 min blip on 10-19 06:29: resident or guest, unknown; GB2 has no BLE).

### 1.2 Stay data that drives everything (max of GB1/GB2, resident time removed)

| Date | 10-02 | 10-05 | 10-08 | 10-10 | 10-12 | 10-13 | 10-14 | 10-15 | 10-16 | 10-17 | 10-18 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Night | 0.36 | 0.51 | 0.25 | 0.15 | 0.37 | **0** | **0** | 0.57 | **0** | **0** | 0 |
| Day (10-22) | 0.04 | 0.10 | 0.14 | 0.00 | 0.04 | 0.03 | 0.00 | 0.00 | **0.46** | **0.22** | 0.02 |

Day fraction exceeds 0.10 on only 7 of the 21 stay days (09-27 .21, 09-29 .21, 10-05 .10, 10-08 .14, 10-09 .16, 10-16 .46, 10-17 .22). Longest in-stay occupancy gap: **51.2 h** (10-13 19:49 to 10-15 23:03); next 17.8 h (10-16 21:23 to 10-17 15:14).
Clean period 10-19..11-09: max night **0.02**, max day **0.051**.

### 1.3 Results

Columns: stay days (of 21, 09-27..10-17); first active day; exit = last active day; clean = false GUEST days 10-19..11-08 (of 21); pre = active days before 09-27 (unlabelled; not counted as false).

| Candidate | stay | first | last | clean | pre | stay days missed |
|---|---|---|---|---|---|---|
| (a) current: night 0.25, day 0.10, exit 2 empty nights, grace 7 d | 18 | 09-28 (lag 1 d) | 10-16 (exit lag -1 d) | 0 | 13 | 09-27, 10-15, **10-17** |
| (b) night 0.30 (entry and hold) | 16 | 09-28 | 10-16 | 0 | 13 | + 10-12, 10-14 |
| (b) night 0.40 (entry and hold) | 13 | 09-28 | 10-16 | 0 | 12 | + 10-10..10-14 |
| (b') entry 0.30 / hold 0.25 | 18 | 09-28 | 10-16 | 0 | 13 | same as (a) |
| (b') entry 0.40 / hold 0.25 | 18 | 09-28 | 10-16 | 0 | 12 | same as (a); drops 09-10 entry |
| (c) night arms, day confirms, same-day or end-of-day (entry 0.30 or 0.40) | = (b') | 09-28 | 10-16 | 0 | 13 / 12 | no change |
| (d) day-only arm 0.10, exit 1 day | 6 | 09-28 | - | 0 | 17 | 15 missed |
| (d) day-only 0.10, exit 2 / 3 / 7 days | 11 / 14 / 21 | 09-27 (same-day arm) | 10-17+ | 0 true triggers (tail spill 1 / 2 / 6) | 23 / 26 / 36 | 10 / 7 / 0 |
| (d) day-only 0.20, exit 7 days | 10 | 09-28 | | 0 true triggers | 35 | 11 |
| **Day veto on the exit (new)**, 0.25 / 0.10 / 2 nights | **19** | 09-28 | **10-18** (+1 d) | **0** | 20 | 09-27, 10-15 |
| exit 3 empty nights (operator already ruled 2) | 20 | 09-28 | 10-18 | 0 | 14 | 09-27 |

Notes.
- (c) adds nothing: the existing "day before + night" entry already fires on the first morning, and the grace path covers the one pre-stay case (09-04) a night-first confirm would catch a day sooner. With grace off, night-first moves 09-05 entry one day earlier; there is no October case where it matters.
- Arrival day 09-27 cannot be caught by any night rule. Only day-only arming sees it (day 0.21 at end of day; same-day arm = lag 0), at a margin of 0.21 vs a 0.10 bar and with 17 to 36 unlabelled non-stay active days. Day-only trigger days: T=0.10: 24 total, 7 in stay, 17 outside, 0 in 10-19..11-08 (clean max 0.051).
- False-exit accounting for the current rule: it is the 10-17 drop (and 10-15, which is the 10-13/10-14 blackout that the grace re-entry on the 10-15 night recovers on 10-16 only).

### 1.4 Exit side: does a day-fraction drop evict faster than empty nights?

Entry fixed at (a). Exit triggered at end of day m if the day fraction is below the threshold for k straight days.

| Exit rule | stay | last active | mid-stay false exit |
|---|---|---|---|
| current (2 empty nights) | 18 | 10-16 | 10-15, 10-17 |
| day < 0.10 x1 (OR with nights) | 14 | 10-13 | yes: 10-05 (.10 float tie), 10-11, 10-14..10-17 |
| day < 0.10 x2 (OR) | 15 | 10-13 | yes: 10-05, 10-14..10-17 |
| day < 0.10 x3 (OR) | 16 | 10-16 | 10-05, 10-14, 10-15, 10-17 |
| day < 0.05 x2 (OR) | 17 | 10-16 | 10-14, 10-15, 10-17 |
| day-only replace, x3 | 17 | 10-20 | 10-05, 10-14, 10-15; exit lag +3 d |
| day-only replace, x5 | 18 | 10-22 | exit lag +5 d |
| day-only replace, x7 | 20 | 10-24 | none; exit lag +7 d |

No day-based exit is both faster and mid-stay-safe: to survive the 10-10..10-15 stretch (6 days under 0.10, partly 0.00) it must wait 7 days, versus about 18 h after the last guest-room occupancy for the 2-night rule. A rolling "no occupancy for G hours" exit has the same limit: in-stay gaps reach 17.8 h and 51.2 h, so G must exceed 17.8 h (about the same as the morning-after-empty-night evaluation) and any G under 51 h false-exits the 10-13/10-14 blackout (the grace recovers it a day later).
The fastest safe change is the veto above: it fixes the one false exit that matters (10-17) at +1 day of exit lag. Exit lag after the guest's last occupancy at 10-18 12:38: veto-rule off at the 10-19 morning evaluation, about 17.5 h; current rule had already evicted a day earlier at 10-17 06:00 while the guest-room was still occupied by a non-resident (day 0.46 / 0.22).

### 1.5 Recommendation and margins

| Parameter | Keep | Margin on this data |
|---|---|---|
| `GUEST_NIGHT_MIN_FRACTION` hold | 0.25 | 0.30 loses 2 stay days, 0.40 loses 5; clean max night 0.02 (12x below) |
| entry night threshold | 0.25 (0.40 optional) | stay entry night 0.72 vs 0.40; 0.40 removes only the unlabelled 09-10 one-night entry |
| `GUEST_STAY_DAY_MIN_FRACTION` | 0.10 | arrival day 0.21 (2.1x); clean max day 0.051 (2x below). Day >= 0.22 never enters the stay |
| exit | 2 empty nights + day veto at 0.10 | recovers 10-17; 10-13/14 still ends the stay then re-enters via grace on 10-15 night |

Producer/consumer: the fractions come from `occupancy_events` (room entry/exit, naive UTC) minus `person_visits` (Bermuda, residents only); sole consumer is `_refresh_guest_stay`. Cost of the veto: one extra read of the day window already fetched in the same span call (`presence.py:6180-6195`), no new state. It is a rung-1 const change plus one condition in the exit `if`; it would need the Tier 2-DB treatment (house-state entry/exit) and a test pinning 10-17. It is not built.

---

## PART 2: HVAC evidence rule for the other house states

### 2.1 What exists (and what does not)

- `HVAC_EVIDENCE_RULE_STATES = ("home_day","home_evening")` (`hvac_const.py:1097`; comment 1090-1096: only these states were measured by `AUDIT_hvac_raw_evidence_gaps_2026_09_26.md`, 82.4 h; "adding a state = a probe + a reviewed change"). Consumers: `hvac_zones.py:932`, `:1482-1487` (`_hvac_rule_for_state`: evidence / night(sleep,waking) / legacy), `hvac.py:5871`, `:6108`.
- `_compute_hvac_occupied` always runs the legacy shadow; for `rule == "legacy"` `_evidence_rule_output` stores `last_ev`/`last_active` and returns the shadow output BEFORE computing the evidence term (`hvac_zones.py:1631-1650`). So in guest, arriving, away and home_night the evidence output is never computed, so it cannot have been logged.
- Persisted comparison: **none.** `ura_activity_log` HVAC actions are climate_write/preset_change/etc. (counted live); no shadow/evidence column. The per-room diagnostic `binary_sensor.<room>_<room>_hvac_occupied` carries `shadow_armed` / `shadow_source` next to the active output (`binary_sensor.py:~950`), which is a comparison only in evidence and night states (where the rule is active). `hvac_occupied_diag` (`hvac_zones.py:2685`) does not expose `last_ev` for legacy states.
- Recorder retention is 8 days (oldest state 2026-11-02 04:12 CST). House-state hours in that window: home_day 80.2 h, sleep 60.1, home_evening 21.1, away 20.4, home_night 6.8, arriving 0.2 (13 episodes), **guest 0**.
- Preset map: guest, arriving, home_night -> `home`; away -> `away` (`hvac_const.py:1282-1291`). So the evidence rule matters in guest/arriving/home_night only through zone retreat (row-1), and in away the preset is already `away`.

### 2.2 Method (reconstruction, not a log)

Probe `.../scratchpad/g/ev2.py` (run on HA, read-only). Window 11-02 05:12Z .. 11-10 07:xx (restart +-15 min excluded), 34 room producers in 3 zones (Media and Master Bath Toilet skipped: no entity; hallways excluded as in code). 15 s grid.
- Evidence model per room: union of `on` intervals of configured motion/presence/occupancy sensors, extended by `ROOM_TYPE_HVAC_HOLD` (or the per-room day override), as in `AUDIT_hvac_raw_evidence_gaps`. It does NOT model camera/BLE override verdicts, grace-hold stamps, the fan-demotion filter or D5 (`coordinator.py:5965-6010`).
- Table A (actual vs model): "legacy" = the recorded `hvac_occupied` entity state (exact shadow output in legacy states).
- Table B (model vs model): legacy model = sensors + `occupancy_timeout` + `ROOM_TYPE_HVAC_TAIL_LEGACY`; evidence model as above. Shared reconstruction error cancels. A "retreat-eligible" event = zone is empty under the evidence model for >= 300 s (live knob 48 grace) while the legacy model is occupied. It is "resumed" if raw evidence returns in the zone before the legacy hold ends (the evidence rule would have retreated a zone a person was still in: the CRIT-1 failure), "released" if legacy also releases (the evidence rule saved lag).
- Calibration: home_day, where the actual output IS the evidence rule, shows the model's own error: Table A act=1 / ev=0 for **4.3 %** of zone-time and act=0 / ev=1 for **2.0 %**. Treat Table A differences below about 5 % as noise.
- Proxy for the guest stay (no raw data exist for October): `occupancy_events` since 09-15, evidence end estimated as exit minus `occupancy_timeout`. It sees only the deterministic lag (timeout + tail - hold) and is blind to mid-session gaps, so it understates "less". Validation: its home_night 4.4 % equals the recorder's 4.4 %; its home_day 5.4 % equals the recorder's 5.5 %.

### 2.3 Results

Table A (zone-hours, 3 zones; recorded legacy vs reconstructed evidence):

| State | zone-h | legacy occ & ev empty ("less") | legacy empty & ev occ ("more") | retreat-length less-runs >= 300 s |
|---|---|---|---|---|
| home_day (evidence live: calibration) | 233.8 | 10.0 h (4.3 %) | 4.7 h (2.0 %) | 21 |
| home_evening (calibration) | 60.3 | 3.2 h (5.4 %) | 1.1 h (1.9 %) | 9 |
| home_night | 20.3 | 2.5 h (12.5 %) | 0.04 h (0.2 %) | 12 |
| away | 59.1 | 3.2 h (5.5 %) | 0.03 h | 16 |
| arriving | 0.6 | 0 | 0.004 h | 0 |
| guest | 0 | no data | no data | no data |

Table B (model vs model; "less" = legacy occupied, evidence empty):

| State | zone-h | less h (%) | more h | runs >= 300 s | of those resumed (premature) | released | runs >= 600 s (resumed) |
|---|---|---|---|---|---|---|---|
| home_day (reference) | 233.9 | 12.8 (5.5 %) | 0 | 41 | **9 (22 %)** | 29 | 3 (0) |
| home_evening (reference) | 60.3 | 2.9 (4.8 %) | 0 | 8 | 0 | 6 | 0 |
| home_night | 20.3 | 0.9 (4.4 %) | 0 | 3 | 0 | 3 | 1 (0) |
| away | 59.1 | 1.1 (1.8 %) | 0 | 5 | 0 | 5 | 0 |
| arriving | 0.6 | 0 | 0 | 0 | 0 | 0 | 0 |
| guest | no recorder hours | | | | | | |

Proxy over the URA DB since 09-20 (occupancy_events, lag component only):

| State | zone-h | less (%) | runs >= 300 s | per zone-h |
|---|---|---|---|---|
| guest (36 episodes, 18.7 h) | 55.8 | 3.3 h (6.0 %) | 12 | 0.215 |
| home_night | 131.1 | 5.7 h (4.4 %) | 19 | 0.145 |
| away | 435.4 | 16.7 h (3.8 %) | 45 | 0.103 |
| arriving | 10.2 | 0.6 h (5.9 %) | 0 | 0 |
| home_day (reference) | 1468 | 78.8 h (5.4 %) | 288 | 0.196 |

Direction: the evidence rule conditions LESS in every state and MORE in none (model "more" is 0 by construction; the actual-vs-model "more" cells are inside the 2 % noise floor). The size of "less" in every non-evidence state (4.4 % to 6.0 %) is the same as home_day (5.4 %), the state the operator already accepted.

### 2.4 Verdicts

| State | Verdict | Numbers and reasoning |
|---|---|---|
| guest | **INSUFFICIENT DATA** (lean SAFE by equivalence) | 0 recorder hours, no raw sensor history for October, no shadow log. Proxy: 6.0 % less over 55.8 zone-h, 0.215 retreat-length events per zone-h vs 0.196 in home_day. What cannot be measured is the unsafe part (premature retreats: 22 % of home_day's retreat-length less-runs, 9 of 41, concentrated in Kitchen/Living Room per the 09-26 audit), and GB1/GB2 have no fan-immune witness (State of Play §4.2b). By code, GUEST maps to `home` and is entered from HOME_DAY/EVENING and left to them, so a stay day should behave as a home_day day; that is an argument, not a measurement. |
| home_night | **INSUFFICIENT DATA** | 20.3 zone-h (6.8 h, 9 episodes). 3 retreat-length events, 0 premature. At home_day's premature rate (0.038 per zone-h) 20.3 zone-h expect 0.8 events, so 0 of 3 proves nothing. Gate B is still unrun (plan §4.3). Sleep-onset gaps in bedrooms are the known risk. |
| arriving | **INSUFFICIENT DATA** | 0.6 zone-h (12 min over 13 episodes in 8 days; 3.8 h house-time since 09-20). Also by design arriving wants instant arming (legacy arms at once; evidence + D5 would add a 60 s persistence wait). |
| away | **INSUFFICIENT DATA, and no value** | 59.1 zone-h, 1.8 % less, 5 events, 0 premature. S1 target is already `away` in this state; the rule would only change room release timing. I did not trace every away-state consumer of `hvac_occupied` (D6 failsafe, D5 shed, pre-arrival), so I do not call it SAFE. |
| NOT SAFE | none identified | no state shows a premature-retreat signal, but none has the hours to show one. |

### 2.5 What would settle it

1. **Add in-system shadow logging (cheapest, and the only way guest ever gets data).** Compute the evidence term before the legacy early-return and keep a per-state counter of "evidence empty while legacy occupied >= grace" and "evidence resumed before legacy release". Display/diagnostic only, so Tier 1. Without it the next guest stay will again leave no data.
2. For guest: the card's own `next` allows "argue daytime GUEST is equivalent to HOME_DAY". The argument above plus the proxy is that argument; the hole is the guest rooms' mid-session gaps. Adding `guest` is a one-line change that I would not call measured.
3. For home_night: run `hvac_raw_evidence_gap_probe.py --states home_night` weekly until about 100 zone-h exist (recorder keeps 8 days, so this takes about 2 months at 6.8 h per 8 days; or take the 43.8 h of house-time since 09-20 only if raw sensor history existed, which it does not).

## Open items and corrections to docs
- `GUEST_MODE.md` §2 and the plan §5.5 describe different exit lengths (plan table says 3, code and const say `GUEST_STAY_EXIT_MAX_NIGHTS = 2`, operator ruling 2026-11-09). Code wins; the plan's rev 6 table does not describe the shipped default.
- The harness docstring says "plan rev 4"; the replay fixture is rev 5/6.
- Nothing in this report was written to the board, memory or code.
