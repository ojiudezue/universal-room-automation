# AUDIT: Envoy reliability recount and frozen-witness reconciliation

Run 2026-10-17 23:17-23:25 CDT (`date`). Read-only. Prober: ura-prober.
Cards: EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 (operator 10-17: "The governor is done. So finish the recount"), EC-SELFHEAL-UNEXPLAINED-RESENDS-1 (operator 10-17: "can we reconcile with the envoy reliability work first?").
Not read in full: HVAC/presence state-of-play docs (not relevant to this topic).

## 0. Answer first

1. **What the recount is.** The resilience card's `next` (kanban.data.yaml:627) and `update_2026_10_15` (:624) say: after 3 clean days post the Ethernet move + GC freeze, re-count Envoy dropouts, and "if dropouts stay ~0 the resilience scope shrinks". The governor (v5.103.66, restarted 2026-10-16 10:47 CDT) was the other gate (`links.blocked_by`, :616). The governor does not touch Envoy availability, so "before/after governor" only matters for the write-side metrics (section 3), not the dropout count.
2. **Dropouts did NOT stay ~0.** Event count fell (6.8/day to 1.7/day) but the shape changed from many short blips to a few very long outages: 586 min (10-15 17:38 to 10-16 03:25) and 714 min (10-16 06:43 to 18:37), and another is open now (since 10-17 23:08:47). Total unavailable minutes per day went UP, not down. The "drops have fallen" reading in the card is an event-count artifact. The scope does not shrink on this evidence.
3. **The frozen witness explains most of the write-side "evidence", none of the connectivity evidence.** Of 622 `pending_write_stuck` rows since 2026-07-19, 311 are certain artifacts (the real Envoy reserve sensor equalled the commanded value when the row fired), 300 are probable artifacts (hourly resolution, cannot prove) and 11 are not provable as artifacts. Every CRITICAL "URA STAND-DOWN" page (28 page-days) rests on that check. The two 10-03 "hardware reports 10.0" stand-downs are proven artifacts (section 4). Envoy flapping/unavailability counts are untouched by the witness.
4. **The frozen witness also hides failures.** Tonight's command of 10 at 18:01:32 CDT never landed (Envoy sensor and cloud number both stayed 9 for 5 h). The watchdog read the frozen number (10.0), saw commanded == 10, and stayed silent. Section 5.
5. **Recommendation.** Ship the witness fix as its own small card (Tier 2) now, before the Tier-3 resilience plan; keep one resilience card for what is left (outage handling, pending-episode back-off, read fallback, token alert). Section 6.

## 1. Sources and method

| Source | Used for |
|---|---|
| HA recorder `/config/home-assistant_v2.db` via `ssh ha "python3 -"` (read-only URI), window 2026-10-10 04:12 to 2026-10-17 23:08 CDT | exact state history of `sensor.envoy_482543015950_battery` (metadata 18389), `sensor.envoy_482543015950_reserve_battery_level` (18390), `number.enpower_482348004678_reserve_battery_level` (941), `number.iq_battery_hacs_battery_reserve` (19446), `sensor.hahm_loop_stalls` (25731), `recorder_runs` |
| HA long-term statistics, `statistics` metadata_id 5663 (`sensor.envoy_..._reserve_battery_level`, hourly min/max/mean, 2026-04-11 to now) | hour-resolution truth for rows before 10-10 |
| URA DB copy in scratchpad (`universal_room_automation.db`, copied 23:17 CDT, newest anomaly row 2026-10-18T04:16Z): `anomaly_log`, `notification_log`, `ura_activity_log` | all verifier rows, pages, governor `reserve_write` rows |
| Code at develop `703a9cb51` | `energy_write_verify.py:369-409`, `:1555-1575`, `:2126-2338`; `energy.py:9691-9726` |

**Dropout definition.** An episode is a transition of `sensor.envoy_482543015950_battery` from a value to `unavailable`, paired with the next non-unavailable row. Episodes starting within -60 s / +300 s of a `recorder_runs.start` (HA restart) are excluded as restart-induced. The production, net-consumption, reserve-sensor and Enpower-number entities show the identical 40 episodes (same integration), so one series stands for all.

**Artifact test for verifier rows.** For each row with a commanded value C at time T: look up the real Envoy reserve sensor at T (recorder, exact, for T >= 10-10) or the hour's min/max in statistics 5663 (T < 10-10).
- ARTIFACT = real sensor == C at T (the battery had obeyed; the frozen number could not have known).
- MIXED = hourly min <= C <= max but min != max (hour contains a transition; cannot prove either way). Reported as a bound, not counted as proven.
- GENUINE = real sensor != C at T.
Caveat: the sensor itself could lag the true hardware state; it is the best available witness (it matched ground truth in both the 10-12/13 and 10-14 episodes, see 5.2).

## 2. The witness defect, re-proven

- Verifier local witness = `_local_entity_for` -> `battery._get_entity("reserve_soc_number", default, role="read")` (`energy_write_verify.py:369-409`), read by `_local_reserve_witness_state` (`:1555-1575`) and by `_pending_watchdog_reserve` (`:2126`, `hw_value` at ~`:2147`). Default is `number.enpower_482348004678_reserve_battery_level` (`energy_const.py:2443`). The docstring at `:1563` says the honest witness is `sensor.envoy_*_reserve_battery_level`; the code does not read it (doc/code mismatch). The `hw_witness: "envoy_reserve_battery_level"` label written into every `pending_write_stuck` row (`:2274`) is a literal string, not the entity actually read.
- Recorder 10-10 to 10-17: the number has exactly two states, `10.0` (50 rows) and `unavailable` (47 rows). The real reserve over the same window took many values (5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 20, 80, 81, 90, 99) on the Envoy sensor and the cloud number.
- URA DB `write_local_witness_divergence`, surface reserve_soc: 2,979 rows all `local_seen=61.0` (2026-07-19 to 08-04) then 3,726 rows all `local_seen=10.0` (2026-08-05 to 10-17). Zero rows ever have commanded == 10 (consistent with a constant 10).
- Every `pending_write_stuck` row has `oracle_seen` = 10.0 (416 rows, 08-05 to 10-17) or 61.0 (206 rows, 07-19 to 08-04). No other value in 622 rows.
- Consequence (from the code, `:2147-2166`): the watchdog's `_compare(commanded, hw_value)` outcome depends only on whether commanded == 10. Commanded != 10 -> "diverged" -> attempts at 15/30/60 min -> attempt 3 = CRITICAL page + hard stand-down (`:2308-2328`). Commanded == 10 -> "converged", always silent.

## 3. The recount

### 3.1 Envoy dropouts (genuine, independent of the witness)

Source: recorder, sensor 18389, restart-excluded. Per-day (CDT):

| Day | Episodes (non-restart) | Unavailable minutes | Note |
|---|---|---|---|
| 10-10 | 4 | 109 | recorder starts 04:12 |
| 10-11 | 10 | 267 | |
| 10-12 | 4 | 297 | |
| 10-13 | 4 | 145 | |
| 10-14 | 12 (+1 restart-adjacent) | 105 | |
| 10-15 | 1 | 587 | opened 17:38 (storm night), closed 10-16 03:25 |
| 10-16 | 1 | 714 | 06:43 to 18:37; governor deploy restart 10:47 fell inside it |
| 10-17 | 3 (one open) | 4 closed + open | 08:46 (2.3 min), 09:01 (1.7 min), **open since 23:08:47** |

Card figures for 10-08/10-09 (6, 7) are cited from `update_2026_10_15` (kanban:624); the recorder here starts 10-10, so I did not re-derive them.

| Period | Episodes | per day | < 10 min | 10-60 min | >= 60 min | Total min | Longest |
|---|---|---|---|---|---|---|---|
| 10-10 to 10-14 (pre Ethernet/GC freeze, 5 d) | 34 | 6.8 | 24 | 4 | 6 | 923 | 264 min |
| 10-15 00:00 to 10-17 23:21 (post, ~2.97 d) | 4 closed + 1 open | 1.7 | 2 | 0 | 2 (+1 open) | 1,304 closed + open | 714 min |

Reading: short blips collapsed (24 in 5 d to 2 in ~3 d), but long outages (>= 60 min) rose from 6 in 5 d to 2 in 3 d plus one open, and downtime did not fall. This is not "3 clean days" yet (the Ethernet/GC-freeze changes date from 10-15; the card's re-count point is 10-18). Three clean days have not elapsed and the days that did elapse contain two multi-hour outages, so the criterion "dropouts stay ~0" is not met.

Cause of the long outages: **unknown from this audit.** The arc's status log says that after the 10-16 deploy restart "the Envoy setup hangs: /info answers but authenticated /ivp/pdm/device_data hangs, needs a gateway reboot" (ARC_energy_coordinator_resilience.md, 2026-10-16 entry); the 06:43 start predates that restart, so it is not caused by the deploy.

Loop-stall side data (`sensor.hahm_loop_stalls`, stalls >= 1 s / total stalls): 10-13 593/595, 10-14 378/470, 10-15 9/683, 10-16 29/1136, 10-17 21/1298. Stalls >= 1 s fell ~95% and stayed down, so the GC freeze worked. The blip collapse follows the stall collapse; the long outages are not explained by stalls (stalls stayed low during them).

### 3.2 Verifier / write-side metrics, frozen-witness artifacts removed

Windows: A = 07-19 to 09-30, B = 10-01 to 10-09, C = 10-10 to 10-16 10:47 CDT (pre governor), D = after governor (>= 2026-10-16T15:47Z). Counts are anomaly rows (one row per evaluation), not pages.

| Metric (surface reserve_soc) | Total | ARTIFACT (certain) | MIXED (hourly bound) | GENUINE | By window A / B / C / D |
|---|---|---|---|---|---|
| `pending_write_stuck` | 622 | 311 | 300 | 11 | 547 (255/285/7) ; 29 (14/15/0) ; 41 (39/0/2) ; 5 (3/0/2) as artifact/mixed/genuine |
| `write_local_witness_divergence` | 6,705 | 5,197 | 1,422 | 86 | A 5,845 ; B 369 ; C 371 (362 artifact, 9 genuine) ; D 120 (111 artifact, 9 genuine) |
| `write_verification_failed` (cloud oracle, NOT the frozen witness) | 226 | 90 vs sensor | 45 | 86 | A 91 ; B 6 ; C 129 (50 artifact, 79 genuine) ; D 0 |
| `write_reverted` (cloud oracle) | 84 | 24 | 0 | 60 | C only (10-11 to 10-14) |

Bounds: the certain-artifact share of `pending_write_stuck` is 50%; including MIXED it is 98% (611/622). Only 11 rows show the real reserve disagreeing with the command at the time, and 4 of them are from 10-16 and 10-17 where the mechanism is known (3 are normal apply lag during the Envoy return at 10-16 03:25-04:36; 1 is the `out_of_range` rejection of a commanded 3, see 5.4). The 7 older GENUINE rows (08-03, 08-26 x2, 09-21, 09-25 x3) show the hourly sensor not at the commanded value; they may be superseded commands (no dispatch history exists before the governor) and are **unproven either way**.

`write_verification_failed` / `write_reverted` are produced from the CLOUD oracle (`oracle_seen` 81, 14, 6, 90), not the frozen number, so they are a separate artifact family: the stale cloud (see 4, item 6).

Pages (notification_log, non-ACK rows, distinct minute, 09-18 to 10-17): "Pending write stuck attempt 1/3" 28 (HIGH), "attempt 3/3" 28 (CRITICAL) and "URA STAND-DOWN" 28 (CRITICAL), always the same 28 events, i.e. 28 of 30 days; "self-heal loop" 21 (CRITICAL, 09-19 to 10-14), "reverted" 6 (CRITICAL, 10-11 to 10-14), "churn" 3, "command failed" 5. Each CRITICAL stand-down also fans out to 4 channels (135 rows for 28 events). All 28 attempt-1/3 and stand-down page events are driven by the `pending_write_stuck` watchdog and therefore by the frozen number; none of them can be called genuine on this evidence except possibly 09-21 and 09-25 (unproven). The self-heal / reverted pages come from the cloud-oracle path (section 4, items 5 and 6).

### 3.3 Governor rows (the "after governor" truth set, new since 10-16)

`ura_activity_log action=reserve_write`, 20 rows from 10-16 18:42 CDT to 10-17 18:01 CDT: 17 applied, 3 failed. Recorder lookups of the Envoy reserve sensor after each applied row:
- Of 13 applied writes that changed the value, 10 landed on the Envoy sensor within 0.1 to 19 min (median ~1.4 min; 19.0 min the slowest), 2 landed late/unknown inside a 15-20 min window (10-16 21:27:35 and 21:57:34, superseded by the next write), and **1 never landed (10-17 18:01:32, value 10, sensor stayed 9 until the Envoy went unavailable at 23:08:47)**.
- 3 failed rows: commanded 3 (SOC 3% "Off-peak hold ... <= target 10%") rejected by Enphase with `ServiceValidationError translation_key=out_of_range` (anomaly_log `battery_write_failed`, 10-17 12:47Z, 13:17Z x2). Cloud number minimum is 5 (the cloud number never went below 5.0 in the recorder). This is a URA desire-clamp defect, independent of the witness and of connectivity.
So the write path itself, when the Envoy is up, mostly works; the loud failure signals were the witness.

## 4. Reconciliation table

| # | Evidence item | Verdict | Proof |
|---|---|---|---|
| 1 | 10-03 15:04 CDT "commanded reserve_soc=80 but hardware reports 10.0 after 3602 s" stand-down (INSTANCE_2026_10_04_overnight) | **ARTIFACT** | anomaly_log: attempt 1/2/3 at 19:23, 19:38, 20:04Z (commanded 80, ages 1189/2092/3603 s). Statistics 5663, hour 15:00 CDT: min=max=mean=80.0. The real reserve was 80 for the whole hour; the number said 10.0. |
| 2 | 10-03 22:05 CDT "reserve_soc=30 ... 3854 s" stand-down | **ARTIFACT** | Attempts 02:20, 02:35, 03:05Z 10-04 (commanded 30). Statistics hour 22:00 CDT: min=max=30.0. |
| 3 | "hardware reports 10.0" text in every Pending-write-stuck message | **ARTIFACT** | `hw_value` = frozen number (`:2147`, `:2262`); label "envoy_reserve_battery_level" at `:2274` is a literal. 622/622 rows have oracle_seen 10.0 or 61.0. |
| 4 | 3,726 + 2,979 `write_local_witness_divergence` rows | **ARTIFACT** | Constant `local_seen`; 5,197 of 6,705 rows have the real sensor equal to the commanded value (section 3.2). 86 genuine rows are mostly the 10-12/13 episode and short lag. |
| 5 | `pending_write_stuck` ladder, hard stand-downs, 3-h cool-off effect (energy_battery.py ~:6487) | **ARTIFACT** in origin; real *effect* | 311 certain + 300 probable artifacts of 622. Behavioural effect is real (log 10-16 23:42 CDT HARD STAND-DOWN, and 5 governor `force_redispatch` rows 10-16 22:57 to 10-17 02:42 re-sending 5 into a battery already at 5). |
| 6 | 10-14 49 sends of 10 / "cloud stuck at 6" (EC-SELFHEAL card O-4) | **MIXED: stale-cloud artifact, not witness** | `write_reverted` 10-14 10:37 to 17:17: 20 rows, all "ARTIFACT" against the sensor (sensor=10, cloud oracle 6.0). Cloud number held 6.0 with no state update 09:08-15:47 CDT while the sensor went 6 -> 8 (10:02) -> 10 (10:18) (recorder). The loop is driven by the stale cloud oracle, a separate defect from the frozen number; the share of the 21 self-heal pages and 6 reverted pages that trace to it was not individually mapped (the 10-14 rows do). |
| 7 | 10-14 15:47 CDT "cloud went 90, watchdog said 10, 3 attempts and CRITICAL page" (O-3) | **ARTIFACT** | cloud 90.0 at 15:47:36, Envoy sensor 90 at 15:48:22; frozen number 10.0. Attempts 21:02/21:22/21:52Z with oracle_seen 10.0. |
| 8 | 10-11 14:56-16:36 and 10-12 14:45-15:44 write_verification_failed rows | **ARTIFACT (stale cloud)** | Cloud oracle said 81.0 / 14.0; sensor already equalled the commanded 15, 20, 90. |
| 9 | 10-12 17:41 to 10-13 ~11:40 write_verification_failed (cmd 10; battery obeys 14) | **GENUINE** | Sensor and cloud both 14 while the command was 10; `battery_write_failed` rows with `control_change_pending` (3 reserve, 6 charge_from_grid, 10-12 to 10-14). Enphase held the change pending. Also the case where the frozen number *wrongly said 10* (false OK for the hardware). |
| 10 | `battery_write_churn` (13 writes/h) 10-11, 10-12, 10-13 | **MIXED** | The re-sends come from the self-heal/pending ladders, whose triggers are in part the genuine pending episode (item 9) and in part the artifact. |
| 11 | Envoy dropout counts (card 10-08..10-14 = 6,7,4,10,4,4,13; recount above) | **GENUINE** | Measured on the Envoy sensors, not on the witness number. Section 3.1. |
| 12 | Long outages 10-15/10-16, open outage tonight | **GENUINE** | `sensor.envoy_..._battery` unavailable 586 and 714 min; open since 23:08:47 CDT. During them the governor and EC correctly hold (the strategy reads "Envoy unavailable - holding", see card INSTANCE_2026_10_04). |
| 13 | Tonight "cloud 9.0 vs commanded 10" | **GENUINE non-landing, masked by the witness** | See section 5.1. |
| 14 | `battery_write_failed` out_of_range, commanded 3 | **GENUINE, URA-side clamp defect** | Cloud number min 5; URA computed desire 3. Not connectivity, not witness. |
| 15 | Card claim "local reserve number is NOT a valid compliance witness on fw 8.x" (INSTANCE_2026_10_14) | **Overstated** | The number is frozen (its own defect). The Envoy sensor is a local reading too and tracked the real reserve in both the 10-12/13 episode (read 14 while the command was 10) and 10-14 (read 90 at 15:48:22). The lesson should be "never accept the frozen number", not "never accept local confirmation". |

## 5. Detail on the non-obvious items

### 5.1 Tonight's 9.0 vs 10
- Governor row: `reserve_write applied path=timer value=10 desire=10 owner=arbitrage_discharge, reason "Mid-peak (shoulder) - discharging ... (degraded telemetry: lkg)"` at 2026-10-17T23:01:32Z = 18:01:32 CDT, 31 s after the HA start at 18:01:01 (recorder_runs). `pre_state` null.
- At that moment `number.iq_battery_hacs_battery_reserve` went `unavailable` at 18:01:30 and `unknown` at 18:02:26, back at `9.0` at 18:02:38. The write came 2 s after the cloud entity went unavailable. "applied" only means the service call did not return an error (`energy.py:9715-9722`: FAILED only if `dispatch_result` is not ok).
- Envoy sensor stayed 9 from 18:01:32 until it went unavailable at 23:08:47. Neither the cloud number nor the Envoy sensor ever read 10 after the command.
- No `pending_write_stuck`, `write_verification_failed` or `write_reverted` row exists after 10-17 14:27Z. The watchdog, comparing against the frozen 10.0, treats commanded 10 as converged (`:2159-2170`).
- Why the cloud-oracle verifier (`verifier.schedule`, `energy.py:9731`) also stayed silent: **unknown** (not investigated; HA journald holds ~18 min, so tonight's log is gone). This should be answered by the witness-fix card's tests.
- Hypothesis (not proven): the write was issued while the cloud entity was down in the restart window and was lost; the 5-hour persistence of 9 is consistent with that. The Envoy went offline at 23:08:47, so it cannot be re-tested until it returns.

### 5.2 The Envoy sensor as a witness (falsification check)
Falsifier for "the sensor is a good witness": it would disagree with ground truth in some episode. Checked: 10-12/13 (sensor 14, battery obeying 14 per EC-RESERVE-CLOUD-DIVERGENCE-1), 10-14 (sensor 90 at 15:48:22, 46 s after the cloud), and 10 of 13 governor writes landed on it within 19 min. It also shows `unavailable` with the Envoy (40 episodes), which the watchdog already handles by abstaining (`:2146-2152`). No contradiction found. Residual risk: it is the Envoy's own configured-reserve reading, so it cannot detect an Enphase pending change that has been accepted by the cloud but not yet delivered to the Envoy (that is exactly what the 10-12/13 episode looked like, and the sensor showed 14 there, so it did detect it).

### 5.3 What the artifact does to the "hard stand-down" behaviour
A stand-down makes the `_result` leg skip same-value re-dispatch of the reserve until desire changes or 3 h pass (card log evidence 10-16 23:42 CDT). It only blocks re-sending a value the battery already has, so the harm is bounded, but it also blocks a re-send that would be needed after a real loss (5.1 is the mirror case).

### 5.4 Not witness-related, newly visible
`out_of_range` rejection of reserve 3 (10-17 07:47-08:17 CDT, three failed governor rows, one HIGH page "Battery command failed: reserve_soc"): desire 3 < Enphase minimum. Belongs on the governor/strategy side (clamp desire to the hardware minimum). Not carded by this audit.

## 6. Recommendation

### 6.1 What remains of the Envoy reliability problem once the witness is fixed
1. **Genuine connectivity**: dropouts (blips now rare; long outages of 586/714 min and one open tonight). Cause unknown; the hang after restart needing a gateway reboot is a known mode. This is the surviving core of EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 and the scope does not shrink on this evidence.
2. **Genuine command problems**: Enphase pending-change episodes (10-12/13, `control_change_pending`), the write lost at restart (5.1, hypothesis), the `out_of_range` clamp.
3. **Stale cloud oracle**: the cloud number can hold a value for hours (10-14: 6.0 for 6.5 h) and drives the self-heal and reverted pages. Not fixed by the witness change; needs its own handling (use the Envoy sensor when the cloud number has not updated, or a freshness gate). Overlaps card item (2).
4. **Resilience items (1)-(4)** on the card remain as written; item (2) (back off while `control_change_pending`, one page per episode) will make most of the current 135-row CRITICAL volume irrelevant, but should be built on a trustworthy signal, hence witness first.

### 6.2 Fold or separate
**Keep the witness fix separate; ship it first.**
- Size/tier: it is a read-path change in `_local_entity_for` / `_local_reserve_witness_state` (`energy_write_verify.py:369-409`, `:1555-1575`), Tier 2 on its own; the resilience card is Tier 3 and still `pre_planning`, gated on the 10-18 recount and two plan reviews. Folding would hold a fix for 1-5 false CRITICAL pages/day behind a Tier-3 plan.
- Operator ruling honoured: no new setting. Behaviour: when the Envoy's own `sensor.*_reserve_battery_level` exists for the config entry, read it; otherwise fall back to today's entity. Do NOT change `energy_reserve_soc_entity`, because it is also the local write-fallback target (`energy_battery.py:842-846`, `:868-877`, per the self-heal card's config-first note). How the sensor is resolved (entity registry by platform/unique id vs name pattern) needs to be checked by the builder; I did not verify that.
- Coupling to the resilience card: it removes `write_local_witness_divergence` as a signal that currently says nothing, and makes `pending_write_stuck` mean something. It should land BEFORE item (2) is designed so that the "one page per episode" logic is built on a witness that can actually be right. Acceptance should cover both directions: (a) no CRITICAL when commanded != 10 and the sensor matches; (b) a real non-landing like 5.1 DOES alert when commanded == 10 and the sensor says 9.
- Add to the resilience card (not the witness card): the cloud-stale oracle handling, the `out_of_range` clamp (or card it separately), and a note that EC-ENPHASE-CONNECTIVITY-RESILIENCE-1's INSTANCE_2026_10_14 "local number not a valid witness" lesson is overstated (item 15).
- Correct the resilience card's re-count criterion: use unavailable *minutes* and episodes >= 60 min, not episode count. Re-run the one-shot on 10-18 per the card; the script is `r.py`/`du.py` equivalent (restart-excluded transitions on `sensor.envoy_482543015950_battery`).

## 7. Limits and unknowns
- Recorder retention starts 2026-10-10 04:12 CDT; earlier dropout counts are the card's.
- Rows before 10-10 are classified by hourly statistics only; 300 `pending_write_stuck` rows are MIXED and shown as a bound.
- Cause of the 10-15/10-16 long outages is unknown. The Ethernet move time is not recorded in the card (only "Envoy is ethernet connected now", kanban:623); I used 10-15 00:00 as the post boundary.
- Why the cloud-oracle verifier did not flag tonight's non-landing is unknown.
- The Envoy is unavailable at report time (since 2026-10-17 23:08:47 CDT, last recorder row); no live re-check of the reserve is possible.
- Scratch files (not committed): `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/{r.py,du.py,an.py,gv.py,rec.json}`.
