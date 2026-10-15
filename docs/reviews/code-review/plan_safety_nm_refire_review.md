# Plan review — SAFETY-NM-REFIRE-UNWIRED-1 (Tier 2-DB, single adversarial plan review)

- Plan: `docs/planning/PLANNING_safety_nm_refire.md` (develop HEAD, incl. "Orchestrator rulings")
- Reviewer: ura-reviewer (plan review), 2026-10-15
- Read first: `docs/Coordinator/SAFETY_COORDINATOR.md` §5 (line 297 known-gap note), `PLANNING_safety_hazard_clear_on_recovery.md` rev 4.

## Verdict: **FIX-REQUIRED** (plan-text fixes only; D1/D2 code shape is sound)

The two code deliverables are correct and minimal. But the plan misdescribes what D1 actually
changes in NM, states an invariant that is wider than the reachable path and false on one path,
and over-claims test red-ness. All fixes go in the plan text and test list; none needs a new mechanism.

## Verification results (greps, not trust)

| # | Question | Result |
|---|---|---|
| 1 | Only NotificationAction site in safety.py? | **Confirmed.** `grep -n "NotificationAction(" safety.py` → single hit `safety.py:2579`. Safety→NM has no other path: the only route is `manager.py:1070-1081` (forwards `action.hazard_type or None`, `action.location or None`). Signals in safety (`SIGNAL_SAFETY_HAZARD` etc.) do not reach NM. |
| 2 | NM re-fire trace | `async_acknowledge` (`notification_manager.py:2859`) → `_start_cooldown` (`:2955`, cooldown from `COOLDOWN_CONFIG[hazard_type]`, `:196-205`) → `_cooldown_expired` (`:3008`) → `_re_evaluate_hazard` (`:3020`) → `coordinator.is_hazard_active(hazard_type, location)` (`:3039`) → re-fire `async_notify(severity=CRITICAL)` (`:3046-3054`). **Cooldown/re-eval exists only after an ACK of a CRITICAL in ALERTING** (`_enter_alerting` `:2515`). |
| 3 | Q2 comfort re-paging | **No regression via the re-eval path.** Only CRITICAL enters ALERTING. Safety CRITICAL hazards are: SMOKE (`safety.py:1864`), CO ≥100 ppm (`NUMERIC_THRESHOLDS` CO CRITICAL), FLOODING (`:1917`, `:1938`). HIGH_CO2/HIGH_TVOC/humidity/OVERHEAT/FREEZE top out at HIGH/MEDIUM (`NUMERIC_THRESHOLDS`, `LOW_HUMIDITY_THRESHOLDS`). Nothing needed in NM policy for Q2. But see F1: D1 changes other NM policies. |
| 4 | Other `is_hazard_active` consumers | **Only NM `:3039`.** Repo grep: defs at `base.py:237`, `safety.py:3398`, `security.py:825`; sole caller `notification_manager.py:3039`. No sensor/dashboard/house-state reader. Hold-aware change is contained. `:roc` stripping preserved by the D2 reference code; existing test `test_safety_hazard_clear_on_recovery.py:515-525` keeps covering it. |

## Findings

**F1 — HIGH — plan omits D1's real blast radius in NM (§5 D1 "Blast radius", §10 Q2, ruling Q2).**
Today every Safety alert reaches NM with `hazard_type=None`, so `is_life_safety_hazard()` is False for
smoke/CO/flooding everywhere in NM. D1 flips all of these at once for safety life-safety tokens:
- CRITICAL repeat cadence: 300 s decay ladder (phase1→phase2→daily) → **30 s fixed, never decays** (`notification_manager.py:2578-2579`, `:2634`).
- Boot-settle collapse exemption (`:1508-1509`).
- DND safety-floor bypass (`:4184`), mute bypass in router (`:4235`), token-bucket bypass (`:3889-3892`, `:3925`, `:4028`).
- Security-image override guard (`:1480`).
- Boot-settle dedup bucket split: key `(coord, hazard_type)` (`:658`) goes from one shared `("safety","")` bucket to per-type buckets.
- Cooldown length: smoke/CO from `DEFAULT_NM_COOLDOWN_DEFAULT` to 2 min; flooding to 5 min (`COOLDOWN_CONFIG`).
These are mostly the intended life-safety contract, but the plan says the only effect is the re-fire gate
and that comfort hazards get "a 300 s non-life-safety re-fire" (wrong: non-CRITICAL never enters ALERTING).
Fix: rewrite D1 blast radius as this list; state each is intended; add a test that a safety smoke
CRITICAL gets `_repeat_phase()=="life_safety"` (fails on develop today).

**F2 — HIGH — INV-REFIRE clause 2/3 is false on the unacked REPEATING path (§1).**
`_repeat_alert` (`notification_manager.py:2645+`) never consults `is_hazard_active`, and NM has no hazard-cleared hook from Safety (grep of NM/safety for a clear signal: none). Repro: smoke at Study A, nobody acks; detector recovers at t=60 s; hold clears at t=360 s; NM keeps paging CRITICAL every **30 s** (post-D1) indefinitely until someone acks. Today it decays (300 s→1800 s→daily). This matters this week (operator away, D1 makes the repeat 10x faster for an already-cleared detector). Fix (pick one, in the plan): (a) narrow INV-REFIRE to "after ACK, at cooldown expiry" and card the repeat-path stop-on-clear as a sibling; or (b) add an `is_hazard_active` check in `_repeat_alert` that drops to IDLE when the source says cleared. (b) touches NM's shared repeat loop; if chosen, it needs its own mutation-anchored test and the security caveat in F4.

**F3 — MEDIUM — invariant set is wrong (§1).**
OVERHEAT is listed as life-safety but is not in `NM_LIFE_SAFETY_HAZARDS` (`const.py:3391-3399`) and is never CRITICAL. FIRE is never emitted by Safety (plan Q3 agrees). WATER_LEAK (HIGH, `safety.py:1868`) and FREEZE_RISK (max HIGH) never enter ALERTING, so clause 1 is vacuous for them. Restate the invariant's domain as CRITICAL safety hazards: `{smoke, carbon_monoxide (≥100 ppm), flooding}`. Note flooding's 5-min cooldown ≥ the 300 s hold, so clause 3 only bites for smoke/CO (120 s).

**F4 — LOW — pre-existing token mismatch in `security.py:825-828`.**
`is_hazard_active` checks `"intrusion"` but security emits `"intruder"` (`const.py:3393-3396` comment). Security alerts therefore never re-fire after cooldown either. Out of this card's scope; card it (do not fold in).

**F5 — MEDIUM — test claims (§5 D3, §8 D3).**
- "All five functions" but six are listed.
- `_true_when_active`, `_false_when_cleared`, `_true_on_relapse_during_hold` **pass on develop today** (D2 only changes the pending-clear branch). They are regression guards, not RED-first tests; say so. Only the D1-carry test, `_false_during_clear_hold`, and the round-trip are RED on develop.
- Round-trip test omits the ACK step. Cooldown starts only in `async_acknowledge` (`:2953`); without an ack the test exercises nothing. Also "re-fired exactly once" is ambiguous, because the re-fire re-enters ALERTING and starts repeats. Specify: count `async_notify` calls from `_re_evaluate_hazard` only, plus a negative twin (recover inside the cooldown, so the hold is pending at expiry → no re-fire, state IDLE). The twin is the discriminating test for clause 3 end to end.
- The relapse test should drive relapse through `_respond_to_hazard` (smoke detector re-on), not by calling `_record_sensor_relapse` directly. The real smoke path re-arms via `had_pending_clear` + `_LIFE_SAFETY_REARM_TYPES` (`safety.py:2487-2492`) and re-pages, which also covers clause 4 when NM is already IDLE.

**F6 — LOW — live acceptance (§8 D1) uses columns not verified.**
The query names `ts`/`coordinator_id`/`hazard_type`/`location` on `notification_log`; verify against the `database.py:4444-4485` DDL in the plan. The D2 live criterion keys on a log string; prefer a `notification_log` re-fire row (ground truth) per the no-display-prose rule.

**F7 — LOW — FLOODING location is a `", ".join(set(...))` (`safety.py:1919`).**
Iteration order of a rebuilt set can differ, so the stored NM `location` may not equal a later re-keyed `_active_hazards` entry → `is_hazard_active` False on a still-active multi-sensor flood. Rare. Note it; a `sorted()` there is a 1-line fix the builder could take in-cycle (Fix LOWs In-Cycle).

## Checklist
- Single emission site: PASS
- Knobs: PASS (no new numbers; the ladder table is accurate, though NM_REPEAT 30 s is newly *reached* by safety, per F1)
- Falsifiable invariant: present but over-broad (F3) and false on REPEATING (F2)
- D2 consumer safety: PASS (sole consumer NM)
- `:roc` behaviour: PASS
- Tests RED on develop: PARTIAL (F5)

## Must-fix before build
F1, F2 (choose a or b and record it), F3, F5. F4 → card. F6/F7 → plan edits (cheap).

---

## Rev 2 re-review (2026-10-15, ura-reviewer)

Read first: `SAFETY_COORDINATOR.md` §5.x (clear hold, I2 re-arm). Verified against develop HEAD source.

### Verdict: **FIX-REQUIRED** (D5 as specified can silence a live smoke/CO page; plan text fixes + one D5 design change)

### F1-F7 resolution check

| # | Status | Evidence |
|---|---|---|
| F1 | **Partly resolved.** B1-B8 sites match code (`notification_manager.py:1480, 1508, 2578, 2634, 658, 3891, 3925, 4028, 4184, 4235`). Missing: `:2700` (repeat-path mute/DND bypass, same class as B3/B4). See R3: the "NON-regression" paragraph is wrong for water_leak/freeze_risk. |
| F2 | **Resolved in intent, but D5 introduces new defects** (R1, R2, R4). |
| F3 | Resolved (`{smoke, carbon_monoxide, flooding}`; flooding 5 min ≥ 300 s noted). |
| F4 | Resolved (carded `SECURITY-REFIRE-INTRUSION-KEY-1`, non-goal). |
| F5 | Mostly resolved (ACK step, relapse via `_respond_to_hazard`, scoped re-fire count). Classification errors remain (R5). |
| F6 | Resolved (columns match the plan's `log_notification` list). D5 live expectation is wrong (R6). |
| F7 | Resolved as D6 (`safety.py:1919, 1926`). T9 is weak (R7). |

### Findings

**R1 — HIGH — D5 + D2 + AlertDeduplicator silence a relapsed smoke/CO (INV-REFIRE clause 4 false, regression vs develop).**
D5 uses the hold-aware predicate, so it drops NM to IDLE on the *first* repeat tick after recovery, not at hold expiry. The re-page on relapse depends on `self._deduplicator.should_alert(hazard)` (`safety.py:2580`), whose CRITICAL window is 60 s (`safety.py:935`), stamped only when it returns True (`:961`). Repro (unacked): smoke ON t=0 (page, dedup stamped 0) → OFF t=5 (hold pending) → repeat tick t=30: `is_hazard_active` False → D5 sets IDLE → smoke ON again t=40: `had_pending_clear` makes `is_new=True` (`safety.py:2487-2492`) but `should_alert` returns False (40 s < 60 s) → no NotificationAction. NM is IDLE, the detector stays ON, and nothing re-pages, because no further `is_new` fires while it stays on. On develop the REPEATING loop would keep paging. Chattering smoke detectors make this reachable. The ACK path is safe: a relapse inside cooldown pops the pending clear and `_re_evaluate_hazard` re-fires at expiry.
Fix (pick one, then record it): (a) give D5 a NON-hold-aware stop condition: stop only when the key is absent from `_active_hazards`, i.e. after the hold has elapsed. This matches what T8 and §8 already describe. D2's hold-awareness stays on the post-ACK path only. Or (b) bypass the deduplicator on the I2 re-arm path. (a) is smaller and contained. Add the t=0/5/30/40 repro as a test.

**R2 — HIGH — D5 fail-closed on empty key and on the boot race.**
- `_recover_state_from_db` restores REPEATING with `hazard_type`/`location` from the DB row (`notification_manager.py:~4898-4911`) and calls `_schedule_repeat()`. Rows written before D1 have NULL `hazard_type` for safety. D5 then calls `is_hazard_active("", "")`, which returns False, so it silences a still-active pre-deploy smoke alert on the first tick after the deploy restart.
- Safety's `_active_hazards` is not restored; it repopulates only once sensor evaluation runs. A recovered REPEATING tick (30 s) that runs before Safety re-raises sees an empty dict → False → IDLE. The re-raise then runs through the 60 s dedup (see R1). That is the same silence.
Fix: treat an empty `hazard_type`/`location` as fail-open, and fail open until Safety reports it has finished initial evaluation (a readiness flag, or a key-present requirement). Clause 5 must list these as error paths. Add tests for both.

**R3 — MEDIUM — the blast-radius "NON-regression" paragraph is wrong for water_leak/freeze_risk.**
`NM_LIFE_SAFETY_HAZARDS` (`const.py:3391-3399`) includes `water_leak` and `freeze_risk`, and `is_life_safety_hazard` also unions an operator extras knob (`_nm_cycle_a.py:200-220`). Post-D1, HIGH water_leak/freeze_risk alerts start bypassing DND, mute and the token bucket, and leave the shared boot-settle bucket (B2-B5, B7). They also get a 10/15 min cooldown key. These are life-safety tokens, so the change is probably intended, but the plan says the opposite (§5 D1 "NON-regression", §6). Restate it, tag it intended, and mention the extras knob.

**R4 — MEDIUM — D5's IDLE transition leaves residue (the plan's "no lingering timer; no residual state" is false).**
`_run_light_pattern` loops `while True` (`notification_manager.py:2437`). Only ack (`:2892-2895`) and teardown cancel it and restore the lights. On D5's unacked path, alert lights keep flashing indefinitely and are never restored. The DB row also stays `acknowledged=0`, so `get_active_critical` can resurrect it at the next restart (freshness-bounded). Fix: D5's terminal branch must cancel `_light_pattern_task`, `await self._restore_alert_lights()`, null `_repeat_unsub`, and mark the row closed (reuse `acknowledge_notification`, or a cleared marker). Add test assertions for each.

**R5 — MEDIUM — test classification errors.**
- T8-fail-open is listed as **F** ("RED on develop"). On develop `_repeat_alert` never calls the predicate, so it re-pages and the test **passes**. It is mutation-anchored post-build only (remove the try/except → it raises). Reclassify it as R/post-build anchor. §8 D3's RED subset is then T1, T4, T6, T7, T7-neg, T8, T9.
- T8: "RED on develop even after D1 alone" holds. Under the R1 fix (a), T8 step 5 is correct as written. Under the current hold-aware D5, T8 never discriminates when IDLE happens; assert the tick at which IDLE occurs.
- Add the R1 relapse test (unacked, relapse inside 60 s) and the R2 empty-key/boot tests. These are the tests that would catch D5 silencing a live hazard.
- §8 D3 says "10 functions", but the table has 11 rows (T1-T9 + T7-neg + T8-fail-open).

**R6 — LOW — the D5 live expectation contradicts the D5 code.**
§8 expects the last row about 30 s after recovery + 300 s. With the hold-aware predicate, repeats stop at recovery + ≤30 s. The R1 fix (a) makes §8 correct. Otherwise rewrite §8.

**R7 — LOW — T9 may pass on develop.**
For two strings, `set()` order inside one process is usually stable whatever the insertion order, so the test can pass on unfixed code. Make it discriminate: run it under two `PYTHONHASHSEED` values in subprocesses, or assert against `sorted()` via the D6 mutation.

### Byte-identity for non-Safety coordinators
Holds as specified. The gate is `coord_id == "safety"` (`COORDINATOR_ID` is `"safety"`, `safety.py:999`; manager keys by `coordinator_id`, `manager.py:443`). Nothing else changes when the branch is skipped. Add a test for the non-safety skip, as §9 B already asks.

### Scenario walk (300 s hold, smoke)
| Path | Result |
|---|---|
| No ack: on, page, off t=100, tick t=120 → IDLE (hold-aware), relapse t=200 (dedup OK) → page, ALERTING | OK, but lights are left flashing (R4) |
| No ack: on t=0, off t=5, tick t=30 → IDLE, relapse t=40 | **VIOLATION**: deduped, silent (R1) |
| Ack t=20, off t=30, relapse t=50 (deduped), cooldown expiry t=140 → active → re-fire | OK |
| Ack t=20, off t=30, expiry t=140 pending → IDLE, relapse t=200 → page | OK |
| Restart with a pre-D1 REPEATING row, or Safety not yet re-raised | **VIOLATION**: silenced (R2) |

### Must-fix before build
R1, R2, R4 (D5 design), R3 and R5 (plan text and test list). R6 and R7 are cheap; fold them in.

---

## Rev 3 re-review (2026-10-15, ura-reviewer)

Read first: `SAFETY_COORDINATOR.md` §5.x. Verified against develop HEAD source by grep/read; T9 seed behaviour run empirically in `.venv-ha`.

### Verdict: **FIX-REQUIRED**. R1 is fixed. D5 can still silence a live smoke/CO page through two new reachable paths (N1, N2), and the tests and live checks for D5 rely on DB rows that are never written (N3).

### R1-R7 resolution check

| # | Status | Evidence |
|---|---|---|
| R1 | **Resolved.** `is_hazard_key_present` ignores the hold. The key stays in `_active_hazards` through the hold. Relapse re-adds it inline at `safety.py:2481-2493` (`had_pending_clear`). Walked t=0/5/30/40: paging never stops, so the 60 s dedup window (`safety.py:935,961`) no longer matters. | |
| R2 | **Partly resolved.** Guards (i)-(iii) are sound. Guard (iv) does not check what its name says (see N1). | |
| R3 | **Resolved.** B9 at `notification_manager.py:2700` (`is_life_safety_hazard`) feeds the DND/router gates at `:2711-2720`. | |
| R4 | **Resolved in shape.** The teardown matches the ack path at `:2886-2900`, but there is an await race (N4). | |
| R5 | **Not resolved.** T7-neg, T10 and T11a pass on develop (N5). | |
| R6 | **Not resolved.** The timing is off and the observable does not exist (N3, N6). | |
| R7 | **Resolved.** Under seeds 0 and 1, `", ".join(set(["Kitchen","Garage"]))` gives `"Kitchen, Garage"`, so T9 is RED on develop under both seeds. pytest can spawn subprocesses (`sys.executable`). See N7. | |

### Findings

**N1 — HIGH (CRITICAL-adjacent) — `_initial_evaluation_complete` does not mean sensors were evaluated. D5 then silences a still-ON smoke alert after restart or reload.**
`_async_periodic_check` (`safety.py:2960-2986`) evaluates no sensors. It only checks flooding escalation and runs `_sweep_hazard_clears`. Safety does not seed itself from current states anywhere: `async_setup` (`:1214-1290`) only subscribes via `async_track_state_change_event` (`:1571`), and nothing in setup loops over `hass.states.get`. `_active_hazards` is populated only by state-change *events*.
Repro (legal): smoke detector ON, CRITICAL REPEATING, then an HA restart or URA reload. A CM reload is the clearest case because entity states don't change. NM `_recover_state_from_db` restores REPEATING with `hazard_type="smoke"`, `location="Kitchen"` (a post-D1 row, so guard (i) passes). Safety's detector stays ON and emits no event, so `_active_hazards` stays `{}`. The first periodic tick (≤60 s) sets the flag True. The next repeat tick sees `is_hazard_key_present=False`, and D5 tears down, marks the row `acknowledged=1`, and goes IDLE. A still-active life-safety alert stops repeating, and because it is acked it will not resurrect at the next restart. On develop it keeps paging. This breaks clause 5(iv).
Fix (pick one, then record it): (a) add a real initial evaluation at the end of `async_setup` that feeds each discovered sensor's current state through the same evaluation path as `_async_sensor_state_changed`, and set the flag only after that; or (b) better, and robust to (c) below: let D5 auto-clear only after a **seen-present → absent** transition. Latch `safety_key_seen=True` the first time `is_hazard_key_present` returns True, scoped to the coordinator instance (store `id(coord)` and reset the latch if it changes). Before that, fail open. Note separately: Safety not re-raising an ON detector after reload is a pre-existing gap and should be carded.
Also answering Q3: the flag is reset on reload, because reload builds a new instance and `__init__` sets it False. It is not reset on teardown (N1c below). It never flips if `async_setup` raises before `:1273`: discovery is wrapped in try/except, so an exception in `_build_room_mappings`/`_discover_sensors` skips scheduling the periodic. D5 then fails open forever, which matches develop and is acceptable, but state it in the plan.
**N1c — MEDIUM — teardown window.** `async_teardown` (`safety.py:3412+`) clears `_active_hazards` but leaves the flag True. The coordinator stays in `cm.coordinators` while the manager tears down the other coordinators (`manager.py:870-880`, each awaiting DB saves), and NM is torn down last (`:904`). A 30 s repeat tick in that window makes D5 auto-clear and DB-ack a live alert, so it does not resurrect after restart. Fix: set the flag False at the top of `async_teardown`, and treat `not coord.enabled` as fail-open. Fix (b) above also covers this if the latch checks the instance and `enabled`.

**N2 — HIGH — NM has a single alert slot. D5 checks only the *latest* CRITICAL, so it silences an earlier still-active one.**
`async_notify` → `_enter_alerting` (`notification_manager.py:2001, 2520`) overwrites `_active_alert_data` on every CRITICAL. Repro (legal: combo smoke/CO detector, or two rooms): smoke:Kitchen CRITICAL t=0 (REPEATING); smoke:Garage (or carbon_monoxide:Kitchen) CRITICAL t=10 overwrites the slot; Garage recovers t=20; sweep pops `smoke:Garage` at ~t=320-380. D5 sees the key absent and goes IDLE + acks. Kitchen is still ON and emits no new event, so nothing re-pages. On develop the loop keeps paging until a human acks. This falsifies "an unacked life-safety alert is never silenced while its hazard is retained". Fix: D5's stop condition must be "Safety retains **no** CRITICAL life-safety key", for example `coord.has_active_critical_life_safety()` over `_active_hazards` with severity CRITICAL. Do not key it to the slot's single key. Add a test (two smoke keys, the later one clears, repeats continue). The post-ACK `_re_evaluate_hazard` has the same single-slot blind spot, but that predates this plan: card it, don't fix it here.

**N3 — HIGH (plan/test authority) — repeat ticks write no `notification_log` row.**
`_repeat_alert` (`:2645-2780`) calls only `_send_pushover/_companion/_whatsapp/_imessage/_tts` (`:2110-2300`). None of those call `log_notification` or `_emit_audit_row`, and `_repeat_alert` has no DB write. So:
- T8 step 2/4/8 and T10 step 8 ("re-page row", "≥4 re-page rows") can never pass as written. They must count `_send_*` calls (or `_schedule_repeat` re-arms).
- §1's falsification bullets 4-5 and 7 ("gap >30 s between re-page rows", "rows past recovery+360 s") and §8 D5 live SQL ("cluster of repeats at ~30 s cadence") check for something that is never written. They would PASS a regression vacuously.
Fix: use the observable that actually exists. Live, that is the terminal `[AUTO-CLEAR]` audit row (`route_reason='auto_cleared:safety_hazard_absent'`), its timestamp relative to the sensor's recorder `off` time, and the original row flipping to `acknowledged=1`. For "kept paging during the hold", either use a channel-side signal or add a DEBUG/INFO log assertion (`"Repeating CRITICAL alert"`, `:2656`) checked in journald.

**N4 — MEDIUM — D5 teardown awaits before it changes state (capture-before-await).**
D5 sets `_alert_state=IDLE` only after awaiting `_restore_alert_lights`, `acknowledge_notification` and `_emit_audit_row`. A human ack in that window passes `async_acknowledge`'s guard (`:2859` — still REPEATING) and runs a second teardown and a second `acknowledge_notification()`. That call (`database.py:4628-4652`, "latest unacked CRITICAL") then acks a *different* row, such as an overwritten earlier alert's row (see N2). `_start_cooldown` arms a timer, and D5 then nulls `_active_alert_data` underneath it. Fix: snapshot the data, set `_alert_state = IDLE` (or a RESOLVING sentinel) and cancel the repeat unsub synchronously *before* the first await. Also place the D5 block before the `os.path.exists` executor await at `:2668`; the plan's "before the fan-out at :2696" is ambiguous.

**N5 — MEDIUM — RED-on-develop classification is still wrong (R5 recurrence).**
- **T7-neg** passes on develop. Without D1, `_re_evaluate_hazard` calls `is_hazard_active("","")`, which returns False, so there are zero re-fires and the state is IDLE. It is RED only on a D1-without-D2 intermediate. Reclassify it as R / intermediate anchor.
- **T10** passes on develop, because the develop loop pages unconditionally. It is a post-build mutation anchor (hold-aware swap), not F.
- **T11a** passes on develop for the same reason. It is a post-build anchor.
- T11b is RED, through its second half only (the IDLE assert). T1, T4, T6, T7, T8 and T9 are confirmed RED.
The correct subset is RED = T1, T4, T6, T7, T8, T9, T11b (7). Post-build anchors = T7-neg, T8-fail-open, T10, T11a. R = T2, T3, T5.
Minor: T10 step 5 says relapse goes through `_record_sensor_relapse`. For smoke it goes inline in `_respond_to_hazard` (`safety.py:2481-2493`). `_record_sensor_relapse` is the leak→flooding path (`:1881`).

**N6 — LOW — §8 timing and SQL errors.**
(a) The sweep runs every 60 s, so the pop lands between recovery+300 s and recovery+360 s. Add up to 30 s for the next repeat tick, and the terminal transition can legitimately arrive at **recovery+390 s**. The 360 s regression threshold would false-alarm; use 390 s, or measure from the pop. (b) The §8 SQL filters `severity='critical'`, but rows store `severity.name` = `'CRITICAL'` (`notification_manager.py:1633`; `database.py:4647` filters `'CRITICAL'`). SQLite `=` is case-sensitive, so the query returns zero rows.

**N7 — LOW — T9 mechanics are under-specified.**
The subprocess must call the production `_check_flooding_escalation`, for example via `SafetyCoordinator.__new__` with `_active_leak_sensors` / `_sensor_locations` / `_leak_start_times` set. Running a copy of the expression would be a hollow anchor (#62). Note also that both seeds 0 and 1 give Kitchen-first, so the plan's "at least one seed" wording is right but understates it.

### Q4 — `acknowledged=1` consumers (auto-clear reuse): CLEAN, with one note
Readers of `notification_log.acknowledged`: `get_active_critical` (`database.py:4671`, `=0`) and `get_active_cooldown` (`:4695`, `=1 AND cooldown_expires IS NOT NULL`). D5 sets no cooldown, so it is never surfaced as a cooldown. No ack-rate metric, digest, NM-REPAGE logic or dashboard reads `acknowledged`/`ack_time` (repo grep, excluding the anomaly_log namesake). Note: `ack_time` on the real row will look like a human ack to any external analytics. The `[AUTO-CLEAR]` audit row disambiguates it, so say so in D4. `acknowledge_notification` acks the "latest unacked CRITICAL", not the episode's row. Combined with N2 (and N4) it can ack the wrong row; fixing N2/N4 bounds this.

### Scenario walk (Rev 3 D5)
| Scenario | Result |
|---|---|
| No ack: ON t=0, OFF t=5, relapse t=40 | OK, paging continuous (R1 fixed) |
| No ack: ON, OFF final at r, no chatter | OK, stops at r+300..390 s |
| ROC suffix (`carbon_monoxide:Loc:roc` retained after threshold key clears) | Keeps paging (conservative, OK) |
| Flooding: composite key; §4-D pops all flooding keys only when every leak sensor is dry (`safety.py:1850-1856`, no hold) | OK, stops ≤30 s after all dry. D6 makes the composite deterministic |
| Ack paths (cooldown / pending / relapse) | Unchanged from Rev 2 walk, OK |
| Restart or reload with detector still ON | **VIOLATION** (N1) |
| Safety teardown before NM teardown | **VIOLATION**, narrow window (N1c) |
| Two concurrent Safety CRITICALs, the later one clears | **VIOLATION** (N2) |
| Pre-D1 NULL row restored | OK, fail-open (i) |

**Can a still-active life-safety alert ever stop repeating?** Yes, through N1, N1c and N2. **Does D5 stop in the normal recovered case?** Yes, at about recovery+300 to 390 s.

### Must-fix before build
N1 (+N1c), N2, N3, N4, N5. Fold in N6 and N7.
