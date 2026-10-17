# PLANNING — SAFETY-NM-REFIRE-UNWIRED-1 (Rev 4): wire `hazard_type`/`location` on the Safety `NotificationAction`, make `is_hazard_active` hold-aware (post-ACK gate ONLY), deterministic flooding location. **D5 WITHDRAWN** — latch-until-ack is the correct life-safety semantics; stop-on-clear in the unacked repeat loop is not shippable in this cycle.

- Card: `SAFETY-NM-REFIRE-UNWIRED-1`
- Blocker: `SAFETY-HAZARD-NEVER-CLEARS-1` — shipped v5.103.61 (2026-10-15, live).
- Tier: **Tier 2-DB** (standing policy for regression-prone life-safety work; cross-coordinator safety ↔ NM; touches a shared primitive — the NM post-ACK re-fire gate — consumed by every coordinator).
- Branch / worktree: `plan/safety-refire` under `.claude/worktrees/plan-safety-refire`.
- Scope: **plan only**. Do not build; do not run the full suite.
- Rev 4 motivation: three successive plan-review rounds (Rev 1 F1-F7, Rev 2 R1-R7, Rev 3 N1-N7, all in `docs/reviews/code-review/plan_safety_nm_refire_review.md`) each returned a NEW HIGH-severity silencing defect against D5 (the unacked REPEATING auto-clear): R1 (hold-aware predicate + 60 s dedup), R2 (empty-key + boot race), N1 (`_initial_evaluation_complete` doesn't mean sensors were evaluated — restart/reload path), N2 (NM single alert slot — second CRITICAL overwrites the first and D5 then silences the earlier). Each round the fix surface widened; D5's invariant kept being falsified. Orchestrator ruling 2026-10-15 (marginal-benefit decomposition): **drop D5 entirely**. Life-safety doctrine is **latch-until-ack** (alarm-panel semantics) — an unacked CRITICAL smoke / CO / flooding keeps repeating until a human acknowledges. The simpler D1+D2+D6 cycle delivers the primary benefit (post-ACK re-fire actually works, DND/mute/token-bucket life-safety classification applies, flooding location is deterministic) without touching the shared `_repeat_alert` primitive.

## 0. Withdrawn: D5 (full evidence, revival trigger)

**What D5 proposed:** inside `_repeat_alert` (`notification_manager.py:2645-2710`), after the state guards and before per-person fan-out, consult the owning coordinator to decide whether the hazard key is still live. When Safety reports "no longer present", transition NM to IDLE, cancel the light-pattern task, restore alert lights, mark the DB row acknowledged, and emit an `[AUTO-CLEAR]` audit row. Supporting mechanisms: a new `Safety.is_hazard_key_present(hazard_type, location)` predicate (non-hold-aware), a new `Safety._initial_evaluation_complete` readiness latch, and a four-way fail-open guard set (empty key / missing CM / predicate exception / boot grace).

**Why withdrawn (reachable silencing defects, three review rounds):**

| Round | Finding | Reachable repro | Severity |
|---|---|---|---|
| Rev 2 R1 | Hold-aware predicate + AlertDeduplicator 60 s window silences a chattering smoke/CO: ON t=0 (page, dedup stamped) → OFF t=5 → tick t=30 (`is_hazard_active=False`, hold pending) → NM IDLE → ON again t=40 inside the 60 s dedup window → `should_alert=False` → no re-page. NM is IDLE, detector is ON, nothing re-pages. | Chattering smoke detector (common failure mode of the real device). | HIGH |
| Rev 2 R2 | Fail-closed on empty key (pre-D1 restored REPEATING rows carry NULL `hazard_type`) and on the boot race (Safety hasn't evaluated sensors yet, `_active_hazards={}`). D5's first tick silences a still-active pre-deploy alert. | Any post-D1 deploy that restarts with a live NULL-row REPEATING state, OR any restart within the 1-min boot grace. | HIGH |
| Rev 3 N1 | **`_initial_evaluation_complete` does not mean what its name says.** `_async_periodic_check` (`safety.py:2960-2986`) evaluates no sensors — it only checks flooding escalation and runs `_sweep_hazard_clears`. Safety has no initial sensor-state pass: `async_setup` only subscribes via `async_track_state_change_event` (`safety.py:1571`); nothing loops over `hass.states.get`. `_active_hazards` is populated by state-change events alone. After an HA restart or URA reload with the smoke detector still ON (no state change emitted), `_active_hazards` stays `{}`, the first periodic tick (≤60 s) flips the readiness flag True regardless, and the next repeat tick sees `is_hazard_key_present=False`. D5 tears down, marks the row `acknowledged=1`, and goes IDLE — a still-active life-safety alert stops repeating and will not resurrect at the next restart. | HA restart or URA reload with a live smoke/CO condition. | HIGH |
| Rev 3 N1c | Teardown window: `async_teardown` clears `_active_hazards` but leaves the readiness flag True; the coordinator sits in `cm.coordinators` while sibling coordinators tear down their DB saves (`manager.py:870-880`), NM teardowns last (`:904`). A 30 s repeat tick in that window makes D5 auto-clear and DB-ack a live alert. | Reload/shutdown race (narrow window, but reachable). | MEDIUM |
| Rev 3 N2 | **NM has a single alert slot.** `_enter_alerting` (`notification_manager.py:2515-2600`) overwrites `_active_alert_data` on every CRITICAL. D5 checks only the LATEST key. Repro (legal, two rooms or a combo smoke/CO device): smoke:Kitchen CRITICAL t=0 (REPEATING); smoke:Garage CRITICAL t=10 overwrites the slot; Garage recovers t=20; sweep pops `smoke:Garage` at ~t=320-380. D5 sees the LATEST key absent, auto-clears, and NM goes IDLE. Kitchen is still ON, emits no new event, and nothing re-pages. On develop the loop keeps paging until a human acks. | Two concurrent CRITICAL life-safety hazards; the later one clears first. | HIGH |
| Rev 3 N3 | **Repeat ticks write no `notification_log` row.** `_repeat_alert` (`:2645-2780`) only calls `_send_pushover/_companion/_whatsapp/_imessage/_tts` — none of those call `log_notification`. D5's unit tests (T8, T10) and live SQL both asserted on `notification_log` repeat rows that are never written; those assertions would vacuously PASS a regression. Test authority defect regardless of correctness. | Every D5 test as drafted. | HIGH |
| Rev 3 N4 | Capture-before-await: D5 awaits teardown before changing `_alert_state`; a human ack landing in that window passes `async_acknowledge`'s guard, runs a second teardown, and `acknowledge_notification` (which targets "latest unacked CRITICAL") then acks a different row — specifically a row for a hazard that was overwritten by N2's single-slot blind spot. | Human ack arriving during D5 teardown await. | MEDIUM |

**Marginal-benefit decomposition (ruling 2026-10-15).** The simple version (keep paging until acked, like an alarm panel) captures the primary benefit: an unacked life-safety hazard is never silenced by Safety-side state at all. The elaborated D5 variant's marginal benefit was "stop paging when the hazard really is gone and the operator is away" — but at the cost of a shared-primitive change (`_repeat_alert`) with a surface area that THREE adversarial reviews collectively found FOUR distinct silencing paths across (R1, R2, N1, N2). Containment machinery (fail-open guards, readiness latch, instance-latch for N1, no-slot-blind-spot predicate for N2) is EVIDENCE of the ingredient risk, not a discount on it. Life-safety doctrine: silent-is-the-defect; **latch-until-ack** is the industry-standard semantics for alarm panels and the correct conservative default here.

**What this means operationally (post-D1 ship).** An unacked CRITICAL smoke / CO / flooding will repeat at a fixed 30 s cadence (`NM_REPEAT_INTERVAL_LIFE_SAFETY`, `const.py:3387`), never decaying, until a human acknowledges. For smoke / CO the cadence used to be the 300 s phase-1 decay ladder (because `hazard_type` was None and `is_life_safety_hazard` was False); post-D1 it becomes 30 s fixed. **This is intended** — the life-safety contract. See §5 D1 blast radius row B1. A future operator complaint of "unacked repeat fatigue" is the revival trigger (below), NOT a bug to fix in-cycle.

**Revival trigger for a future D5-redux cycle.** Any ONE of:
- Operator reports unacked-repeat fatigue (e.g. 30 s cadence overnight after a known-false smoke event the operator chose not to ack from away). The right first response is a **cadence knob** (promote `NM_REPEAT_INTERVAL_LIFE_SAFETY` from Rung 1 → Rung 2 options-flow, or add a per-coordinator override), not an auto-clear.
- AND the Safety Coordinator gains both (a) a real initial sensor-state pass in `async_setup` that seeds `_active_hazards` from current `hass.states.get` reads for every discovered detector, and (b) a mechanism for NM to track more than one concurrent CRITICAL alert (either multi-slot `_active_alert_data` or a per-key repeat scheduler). The N1 and N2 preconditions must be fixed first; D5 cannot be built safely on top of today's single-slot NM + event-only Safety priming.

Any revival MUST re-enter the Tier 2-DB plan-review flow and re-verify the four reachable repros above (R1, R2, N1, N2) are provably unreachable BEFORE build dispatch.

**Carded as `SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1`** (Rung-2 cadence knob — small, clean, no shared-primitive risk) and **`SAFETY-NO-INITIAL-SENSOR-PASS-1`** (the N1 precondition — Safety should seed `_active_hazards` from current states at setup end; see §0b below for the discriminator).

## 0a. Rev 3 → Rev 4 resolution table

| # | Severity | Finding | Resolution in Rev 4 |
|---|---|---|---|
| N1 | HIGH (D5) | `_initial_evaluation_complete` doesn't guarantee sensors were evaluated; D5 auto-clears a still-ON detector after restart/reload. | D5 withdrawn (§0). The underlying "Safety has no initial sensor-state pass" is a **pre-existing gap** carded as `SAFETY-NO-INITIAL-SENSOR-PASS-1`. See §0b for its interaction with D2 (the post-ACK path on develop and under D1+D2). |
| N1c | MEDIUM (D5) | Teardown window race. | D5 withdrawn — moot. |
| N2 | HIGH (D5) | NM single alert slot blinds D5 to overwritten CRITICALs. | D5 withdrawn — moot. The single-slot limitation remains on the post-ACK `_re_evaluate_hazard` path (pre-existing); not a regression vs develop, carded under `NM-MULTI-ALERT-TRACKING-1` for future work and the D5-revival precondition (§0). |
| N3 | HIGH (test authority) | Repeat ticks write no `notification_log` row; D5's unit asserts and live SQL were vacuous. | D5 withdrawn removes those tests entirely. The remaining tests (D1, D2, D6) assert on observables that DO exist: `notification_log` rows written per delivered channel (`notification_manager.py:1678-1899`; `async_notify` is at :1326, and :551 is dry-run-only `_log_dry_run`), `_repeat_phase()` return value, `is_hazard_active` return value, and the subprocess-captured output of the D6 flooding-location composition. See §5 D3 and §8. Where a repeat-cadence observable IS needed (none remain post-withdrawal), the correct observables are: counts of `_send_pushover/_companion/_whatsapp/_imessage/_tts` calls (the real repeat sinks), re-arms of `_schedule_repeat`, or the DEBUG log at `notification_manager.py:2656` (`"Repeating CRITICAL alert"`). |
| N4 | MEDIUM (D5) | Capture-before-await race. | D5 withdrawn — moot. |
| N5 | MEDIUM (test classification) | T7-neg, T10, T11a mis-classed as F; T10 relapse via wrong path; count errors. | Rewritten in §5 D3: T10 / T11a / T11b removed with D5. T7-neg re-classed **R / intermediate anchor** (passes on develop because `is_hazard_active("", "")` returns False → zero re-fires → IDLE; only RED on a D1-without-D2 intermediate). T2, T3, T5 confirmed R. T1, T4, T6, T7, T9 confirmed F. Final count: **7 tests** (not 14). RED-on-develop subset: T1, T4, T6, T7, T9 (5). R / regression guards: T2, T3, T5, T7-neg (4; T7-neg is R-with-intermediate-anchor). |
| N6 | LOW (SQL / timing) | §8 SQL used `severity='critical'` lowercase; rows store `'CRITICAL'`. Timing arithmetic 300 s → 390 s off due to 60 s sweep. | SQL fixed to `severity='CRITICAL'` (`notification_manager.py:1633` writes `severity.name`; `database.py:4647` filters uppercase). D5 timing section removed (D5 withdrawn). D2 live expectation unaffected by the sweep arithmetic (post-ACK re-fire fires at `ack_time + cooldown`, independent of the clear-hold sweep). |
| N7 | LOW (T9 mechanics) | T9 subprocess must call the real `_check_flooding_escalation` to be a non-hollow anchor. | T9 reshaped in §5 D3: the subprocess constructs a `SafetyCoordinator` instance via `__new__` with `_active_leak_sensors`, `_sensor_locations`, `_leak_start_times` populated, then calls the **real** `_check_flooding_escalation` method and asserts the resulting `Hazard.location` string. The two seeds (`PYTHONHASHSEED=0` and `=1`) exercise the real production code path; a copy of the join expression would be a hollow anchor (#62) and is explicitly forbidden. |

## 0b. Post-ACK gate × "Safety has no initial sensor-state pass" (honest comparison)

**Question raised by orchestrator:** does N1 (Safety doesn't seed `_active_hazards` at setup; it waits for state-change events) also break D2's post-ACK re-fire gate? Walk-through:

- **After an HA restart with smoke detector still ON (no new state change event emitted):**
  - `_active_hazards` stays `{}` on the Safety side.
  - On the NM side, `_recover_state_from_db` may restore a COOLDOWN state if the ack happened pre-restart and cooldown hadn't expired; or it may restore nothing. Assume cooldown is live and expires post-restart.
  - `_cooldown_expired` → `_re_evaluate_hazard` → `coordinator.is_hazard_active("smoke", "Kitchen")` → iterates empty `_active_hazards` → returns **False** → **no re-fire**. NM goes IDLE.

- **Develop today (hazard_type=None everywhere):**
  - `_re_evaluate_hazard` calls `coordinator.is_hazard_active("", "")` → iterates `_active_hazards` (whatever is in there) → returns **False** (no key matches `":"`) → **no re-fire**. NM goes IDLE.

- **Verdict:** D1+D2 does **not regress** the post-ACK path for a still-ON-after-restart smoke/CO. **Both** develop and D1+D2 fail to re-fire in this case. The reason differs (develop fails because `hazard_type` is empty; D1+D2 fails because `_active_hazards` is empty on the Safety side), but the operator-visible outcome is identical: no re-page after cooldown of an acked-but-still-live hazard that survived a restart.

- **For a continuously-live hazard with no restart** (the normal case): the detector state-change events keep `_active_hazards` populated, D2 returns True at cooldown expiry, re-fire happens. D1+D2 is a **strict improvement** on this normal path (develop never re-fires because `hazard_type` is empty).

- **Classification:** the restart-with-no-event-emission silence is a **pre-existing gap**, carded as `SAFETY-NO-INITIAL-SENSOR-PASS-1`. **Not fixed here.** The minimal fix is non-obvious (which sensors to seed, how to classify current-state ON vs edge-trigger, where to call it such that it runs AFTER the room/sensor discovery completes), and conflating it with this cycle re-opens the D5-shaped scope that just got withdrawn. Honest documentation of the gap goes in §6 Non-goals and the companion card.

- **Discriminator for the carded gap:** post-D1 deploy, induce a HA restart while a smoke detector is CRITICAL and acked (within cooldown). Expected post-fix: a re-fire `notification_log` row with `hazard_type='smoke'` within 120 s of the restart. Pre-fix (today, including after D1+D2): no re-fire row. The card tracks that observation.

## 1. Falsifiable invariant (Rev 4 — D1 + D2 only, post-ACK path)

> **INV-REFIRE (Rev 4)**: Let `H_safety_crit = {smoke, carbon_monoxide, flooding}` be the subset of `HazardType` the Safety Coordinator emits at CRITICAL severity (intersected with `const.NM_LIFE_SAFETY_HAZARDS`). For every hazard emitted by Safety with `hazard_type ∈ H_safety_crit`:
>
> 1. **Still-active after ACK ⇒ exactly one re-page at cooldown expiry (post-ACK path).** When `_re_evaluate_hazard` (`notification_manager.py:3020-3060`) runs, if the hazard remains in `_active_hazards` with no pending clear hold on a quiet detector, `coordinator.is_hazard_active(hazard_type, location)` MUST return True, and NM MUST emit exactly one `async_notify(severity=CRITICAL)` call from `_re_evaluate_hazard` carrying the same `hazard_type` and `location`.
> 2. **Pending clear during cooldown ⇒ no re-page.** If every raising sensor has recovered and the 300 s clear hold is pending (`key in _hazard_clear_pending`, `_hazard_raising_sensors[key]` empty), `coordinator.is_hazard_active(...)` MUST return False at `_cooldown_expired`, and NM MUST transition to IDLE with zero re-fire calls.
> 3. **Relapse during cooldown ⇒ re-page at expiry.** If the hold was pending and a contributor relapsed through the smoke/CO/leak path (`_respond_to_hazard` → `had_pending_clear` + `_LIFE_SAFETY_REARM_TYPES` at `safety.py:2487-2492`), the key returns to `_active_hazards` without pending-clear, `is_hazard_active` returns True, and NM re-fires exactly once.
> 4. **Unacked ⇒ latch-until-ack (life-safety doctrine, operator ruling 2026-10-15).** The `_repeat_alert` loop on an unacked CRITICAL life-safety hazard is NOT silenced by Safety-side state at any point. Paging continues at the fixed 30 s life-safety cadence (`NM_REPEAT_INTERVAL_LIFE_SAFETY`, `const.py:3387`) until the operator acknowledges via `async_acknowledge`. This is the alarm-panel default. Any mechanism that silences the loop based on Safety-side signals is out of scope for this cycle (see §0 D5 withdrawal).
>
> **Falsification observations (any one disproves the plan):**
> - A `notification_log` row where NM cooldown expired on a still-active smoke/CO hazard and no re-page row followed within one `_re_evaluate_hazard` tick → clause 1 false.
> - A `_re_evaluate_hazard` re-fire call with `hazard_type == ""` or `location == ""` (either as a `notification_log` NULL/empty column or in the structured log line at `notification_manager.py:3042-3044`) → D1 did not land.
> - A re-fire row whose `hazard_type` key was in `_hazard_clear_pending` with no raising sensors at the moment of cooldown expiry → clause 2 false (D2 regression).
> - After a relapse that cancels a pending clear, no re-fire row at the next cooldown expiry → clause 3 false.
> - **NOT falsified by:** an unacked loop paging indefinitely at 30 s cadence; a post-restart live-hazard failing to re-fire post-ACK (pre-existing gap, carded).

**Scope note:** the Rev 3 invariant covered the unacked REPEATING path as well. Rev 4 removes those clauses — latch-until-ack means the unacked path has no auto-stop condition this cycle governs.

## 2. Institutional context verified

Grep surfaces consulted: `const.py`, `config_flow.py`, `options_flow.py`, `sensor.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`, `services.yaml`, `domain_coordinators/*.py`, `database.py`, `docs/Coordinator/*`, `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md`.

Prior-art verdicts (REUSED / NEW with file:line):

- **`NotificationAction.hazard_type` field** — REUSED (`base.py:136`).
- **`NM.async_notify(hazard_type, location)`** — REUSED (`notification_manager.py:530-558`).
- **`BaseCoordinator.is_hazard_active`** — REUSED (`base.py:237`); override at `safety.py:3398-3410`. D2 modifies the Safety override to hold-aware; the base signature is unchanged.
- **~~`Safety.is_hazard_key_present`~~** — **WITHDRAWN** (D5 withdrawal). No new predicate added.
- **~~`Safety._initial_evaluation_complete`~~** — **WITHDRAWN** (D5 withdrawal). No readiness flag added. The N1 critique (the flag didn't mean what its name said because Safety has no initial sensor-state pass) is why D5 is withdrawn; the underlying pre-existing gap is carded separately as `SAFETY-NO-INITIAL-SENSOR-PASS-1`.
- **`_hazard_clear_pending`** — REUSED (`safety.py:1043, 2870, 2878, 2885, 2890, 2927, 2944, 2952, 3051, 3441`). Read-only (membership check) in this cycle.
- **`_active_hazards`** — REUSED (`safety.py:1037, 2493, 2882, 2924, 2944, 2969, 3048, 3057, 3077, 3085, 3109-3133, 3153, 3185, 3214-3227, 3406, 3438`). Read-only (membership check) in D2.
- **`_hazard_raising_sensors`** — REUSED. The emptiness-of-raising-contributors check is the mechanism distinguishing "pending hold" from "live hazard" in D2.
- **`HazardType` emitted at CRITICAL by Safety** — ENUMERATED via grep of `Severity.CRITICAL` inside `Hazard(` constructors in `safety.py`: `smoke` (`safety.py:1864`), `carbon_monoxide` ≥100 ppm (via `NUMERIC_THRESHOLDS`), `flooding` (`safety.py:1917-1919, :1938`). WATER_LEAK tops out at HIGH; FREEZE_RISK / OVERHEAT / HIGH_CO2 / HIGH_TVOC / HUMIDITY top out at HIGH or MEDIUM — none ever enter NM's ALERTING state. **FIRE** is defined in the enum but never produced in `safety.py`. This grounds the Rev 4 invariant domain. **Correction (Review B-HIGH-1, 2026-10-15):** WATER_LEAK does NOT top out at HIGH. The rate-of-change path raises a humidity rise in any non-bathroom room as `water_leak` (`safety.py:868-870`) at z-score severity, which is CRITICAL at z>=5 (`safety.py:763-766`; Hazard built `safety.py:1789-1817`, `from_roc=True`). ROC freeze is not a path (temperature ROC maps to HVAC_FAILURE/OVERHEAT), but freeze_risk is ruled into the same schedule set for consistency. Resolution: `NM_SCHEDULED_LIFE_SAFETY_HAZARDS` = smoke, carbon_monoxide, flooding, fire, water_leak, freeze_risk — every life-safety token Safety emits follows the operator's repeat schedule (D7); intruder and extras-knob tokens stay at 30 s.
- **`NM_LIFE_SAFETY_HAZARDS`** — REUSED (`const.py:3391-3399`). Contents: `smoke, carbon_monoxide, fire, intruder, water_leak, freeze_risk`. The `water_leak`/`freeze_risk` inclusion is deliberate (R3). Union with operator extras knob (`_nm_cycle_a.py:200-220`).
- **NM cooldown constants** — REUSED (`const.py` COOLDOWN_CONFIG): `DEFAULT_NM_COOLDOWN_SMOKE=2`, `_CO=2`, `_FLOODING=5`, `_WATER_LEAK=10`, `_FREEZE=15`. Not touched.
- **Life-safety repeat cadence** — REUSED (`NM_REPEAT_INTERVAL_LIFE_SAFETY = 30 s`, `const.py:3387`). Not touched. Operator-facing consequence: unacked CRITICAL smoke/CO/flooding paging goes from a 300 s decay ladder (develop) to a fixed 30 s cadence (post-D1), never decaying — see §5 D1 row B1. A future cadence knob (Rung 2) is carded as `SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1`.
- **`is_life_safety_hazard`** — READ-ONLY. Nine policy branches flip for Safety CRITICAL (smoke/CO/flooding) and HIGH (water_leak/freeze_risk) tokens when D1 lands; enumerated in §5 D1 table.
- **Precedent for `hazard_type`-wired NotificationAction** — REUSED. Sites that already pass `hazard_type`+`location`: `perimeter_alert.py:1529, 2968`, `zone_monitoring_tripwire.py:125`, `button.py:2373` (test), `energy_battery.py:1313, 1507, 1599, 1769, 1855`. Safety is the single outlier.
- **Existing NotificationAction site in safety** — ENUMERATED, one and only one: `safety.py:2579-2587` inside `_respond_to_hazard` (`rg -n 'NotificationAction\(' safety.py` → single match).
- **Post-ACK re-fire site (D2 sole consumer)** — REUSED (`notification_manager.py:3034-3039` inside `_re_evaluate_hazard`). The only `is_hazard_active` call-site in the integration (`rg -n 'is_hazard_active' custom_components/`).

Prior planning docs consulted:
- `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` rev 4 — read §4-G (`is_hazard_active` suffix-aware), §10 (SAFETY-NM-REFIRE-UNWIRED fold-out).
- `docs/reviews/code-review/plan_safety_nm_refire_review.md` — Rev 1 (F1-F7), Rev 2 (R1-R7), Rev 3 (N1-N7).

Memory bodies pulled: CLAUDE.md standing rules (No Fabrication, Config-First, Numbers-Get-Knobs, Tier-2-DB default, Fix LOWs In-Cycle, Suppression needs a discharge, Extend existing never rebuild, Marginal-benefit pushback, Do the robust fix don't band-aid+card — tempered here by the orchestrator ruling that D5's robust fix is "latch-until-ack is the robust fix", not "stop-on-clear done harder").

Design docs read: `docs/Coordinator/SAFETY_COORDINATOR.md` §5 clear-on-recovery (line 293: `HAZARD_MIN_HOLD_S = 300` and the per-minute sweep).

Code locations surveyed end-to-end:
- `safety.py:1013-1290` (`__init__` + `async_setup`; readiness-flag plan withdrawn)
- `safety.py:1864-1940` (CRITICAL emission sites: smoke, flooding)
- `safety.py:2465-2600` (`_respond_to_hazard` + `NotificationAction` emit; re-arm at `:2487-2492`)
- `safety.py:2860-2954` (clear-hold machinery, `_record_sensor_recovery`, `_try_clear_if_quiet`, `_sweep_hazard_clears`)
- `safety.py:2960-2986` (`_async_periodic_check` — contains no sensor evaluation, confirms N1 critique)
- `safety.py:3398-3410` (`is_hazard_active` — D2 target)
- `manager.py:1070-1095` (NOTIFICATION dispatch — forwards `action.hazard_type or None` and `action.location or None`)
- `notification_manager.py:1326` (`async_notify`); per-channel `notification_log` rows at `:1678-1899` (`:520-560` is `_log_dry_run`, dry-run only)
- `notification_manager.py:2515-2600` (`_enter_alerting` — only CRITICAL enters; single-slot `_active_alert_data`, N2's precondition)
- `notification_manager.py:2645-2800` (`_repeat_alert` — **not touched this cycle**, D5 withdrawn)
- `notification_manager.py:2859-2954` (`async_acknowledge` → ack-path teardown — reference only)
- `notification_manager.py:2953-3060` (`_start_cooldown` → `_cooldown_expired` → `_re_evaluate_hazard` — D2's sole consumer)
- `notification_manager.py:4880-4913` (`_recover_state_from_db` REPEATING restore — relevant to N1/N2 discussion, not touched)
- `base.py:120-240` (`NotificationAction` schema + base `is_hazard_active`)
- `const.py` COOLDOWN_CONFIG + `NM_LIFE_SAFETY_HAZARDS` + `NM_REPEAT_*`
- `_nm_cycle_a.py:200-220` (extras-knob union into life-safety set — R3)
- `database.py:4440-4490` (`log_notification` INSERT column order; `database.py:4628-4660` for ack path reference).

## 3. Config-first check

- No configuration (knob, options-flow field, HA setting, operator action) resolves this: the data to be propagated (hazard type + location) are **computed inside the emitter** and are not operator-settable. Live NM cooldown values are tunable but irrelevant to the symptom (`is_hazard_active('','')` always-False, independent of cooldown length).
- **Future knob (carded, not this cycle):** `SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1` promotes `NM_REPEAT_INTERVAL_LIFE_SAFETY` from Rung 1 to a Rung-2 options-flow field so the operator can soften the 30 s cadence if unacked-repeat fatigue surfaces.
- Verdict: **Code change required.** Config-first checked; no knob turn substitutes for this cycle's deliverables.

## 4. Producer and Consumer map

**Producer** (`safety.py:2465-2587`):
- Arithmetic: `hazard.type.value` (StrEnum → canonical token) and `hazard.location` (room/zone string populated at every `Hazard(...)` construction site: `safety.py:1864, 1891, 1917, 1938, 1805, 2073, 2175, 2200, 2229, 2404, 2446`).
- Dependency health: both are set at every `Hazard` construction site; the `@dataclass` requires both as keyword args. Flooding's `location` composition (D6 target) is the only non-deterministic string in the set.

**Consumers:**
- `manager.py:1070-1081` (trust, forwards both into NM).
- `notification_manager.py:1678-1899` (trust, log rows, one per delivered channel): write `hazard_type` + `location` into `notification_log`.
- `notification_manager.py:3034-3039` (trust, post-ACK re-fire gate): calls `coordinator.is_hazard_active(hazard_type, location)` — D2 sole consumer.
- `notification_manager.py:2578-2579, 2634, 1508-1509, 4184, 4235, 3889-3892, 3925, 4028, 1480, 658, 2700` (policy): read `hazard_type` for life-safety classification. **R3 blast radius** — see §5 D1.
- `sensor.py:8341, 8436, 8548, 14169` (display): dashboard readouts.
- `database.py:4440-4490` (storage, `log_notification`): persists both.
- **~~`notification_manager.py:2645-2710` (`_repeat_alert`)~~** — **NOT a consumer this cycle** (D5 withdrawn). The unacked REPEATING loop does not read Safety-side state.

## 5. Deliverables

### D1 — Populate `hazard_type` + `location` on the Safety `NotificationAction`

**File / line:** `custom_components/universal_room_automation/domain_coordinators/safety.py:2579-2587`

**Change (surgical):** inside the one `NotificationAction(...)` constructor, add two keyword arguments:

```python
hazard_type=hazard.type.value,
location=hazard.location,
```

That is it. No new import; `hazard.type.value` is already the exact token written to `notification_log` by the activity-logger block one scope up (`safety.py:2537`), so the two sites now agree on their key.

**Blast radius in NM (R3-corrected, carried from Rev 3).** Today every Safety alert reaches NM with `hazard_type=None`, so `is_life_safety_hazard()` returns False everywhere in NM. D1 flips the following NM policies at once for Safety life-safety tokens — the full set emitted at life-safety classification: `smoke`, `carbon_monoxide`, `flooding` (CRITICAL), `water_leak`, `freeze_risk` (HIGH), plus any tokens the operator has added via the `_nm_cycle_a.py:200-220` extras knob:

| # | Site | Behaviour today (hazard_type=None) | Behaviour post-D1 | Verdict |
|---|---|---|---|---|
| B1 | `_repeat_interval_for_active_alert` (`notification_manager.py:2578-2579`) + `_repeat_phase` (`:2634`) | 300 s decay ladder (`phase1=300 s` → `phase2` after `PHASE1_WINDOW_S` → `daily` after `DAILY_AFTER_S`). | Fixed **30 s** (`NM_REPEAT_INTERVAL_LIFE_SAFETY`), **never decays**. CRITICAL only (HIGH never enters ALERTING). | **SUPERSEDED by D7 (Rev 4.2 + review B-HIGH-1):** every Safety life-safety CRITICAL (smoke, CO, flooding, ROC water_leak; plus fire/freeze_risk tokens) follows the operator's repeat schedule — default Standard ladder (5 min / 30 min / daily), Fast start, or Urgent 30 s. Intruder and extras stay 30 s flat. Unacked path remains **latch-until-ack** per §0. |
| B2 | Boot-settle collapse exemption (`notification_manager.py:1508-1509`) | Smoke/CO/flooding/leak/freeze alerts raised during the boot-settle window could be collapsed into the dedup bucket (silent). | Boot-settle collapse is bypassed for life-safety hazards — the alert raises immediately. | **INTENDED.** A life-safety hazard during boot must not be silenced. |
| B3 | DND safety floor at `async_notify` (`notification_manager.py:4184`) | DND veto applies, suppressing CRITICAL smoke/CO/flooding + HIGH water_leak/freeze_risk during quiet hours. | DND bypass applied — life-safety alerts page through DND. | **INTENDED.** DND safety floor is the stated design (R3: water_leak/freeze_risk inclusion deliberate). |
| B4 | Router per-recipient mute bypass (`notification_manager.py:4235`) | Per-recipient mute suppresses even CRITICAL smoke/CO (and HIGH water_leak/freeze_risk). | Per-recipient mute bypassed for life-safety. | **INTENDED (R3).** |
| B5 | Token-bucket bypass (`notification_manager.py:3889-3892, 3925, 4028`) | Rate limiter can drop life-safety alerts in a burst. | Token bucket bypassed for life-safety; always admitted. | **INTENDED (R3).** |
| B6 | Security-image override guard (`notification_manager.py:1480`) | A smoke/leak alert during a security image path could be deprioritised. | Life-safety path takes precedence. | **INTENDED.** |
| B7 | Boot-settle dedup bucket key (`notification_manager.py:658`) | Key `(coord, hazard_type)` was `("safety", "")` — a single shared bucket for all Safety hazards during boot. | Per-hazard buckets: `("safety","smoke")`, `("safety","carbon_monoxide")`, `("safety","flooding")`, `("safety","water_leak")`, `("safety","freeze_risk")`. | **INTENDED.** Dedup becomes correct per-hazard. |
| B8 | COOLDOWN_CONFIG lookup (post-ACK path, `notification_manager.py:196-205`) | Cooldown falls back to `DEFAULT_NM_COOLDOWN_DEFAULT` (keyed on `""`). CRITICAL-only path. | Smoke/CO → 120 s; flooding → 5 min. HIGH water_leak/freeze_risk never ACK through this gate (don't enter ALERTING). | **INTENDED.** Operator-tunable per-hazard cadence. |
| B9 | `_repeat_alert` life-safety mute/DND bypass (`notification_manager.py:2700` → `_recipient_bypasses_dnd` / `_route_for_recipient` at `:2711-2720`) | Repeat ticks (CRITICAL only, so smoke/CO/flooding) honour per-recipient DND + mute. | Repeats bypass DND and mute for life-safety CRITICALs. | **INTENDED.** Mirrors B3/B4 on the repeat path. |
| B10 | Alert-light pattern (`notification_manager.py:1688` → `LIGHT_PATTERNS` `:2345`) | Every Safety alert shows the yellow "warning" pulse (no hazard_type). | Smoke/CO flash fast orange; flooding pulses blue. | **INTENDED** (hazard-specific patterns now reachable). |
| B11 | TTS night DND bypass (`notification_manager.py:1668/1672`) | Safety TTS follows DND (no hazard_type → not life-safety). | House speakers announce smoke/CO overnight despite DND. | **INTENDED** for life safety; called out for the deploy-timing decision (§8). |

**R3 restatement:** `water_leak` and `freeze_risk` are deliberately in `NM_LIFE_SAFETY_HAZARDS` (`const.py:3391-3399`); after D1 their HIGH-severity alerts begin to bypass DND, per-recipient mute, the token bucket, and leave the shared boot-settle bucket (B2-B5, B7). ~~They do NOT enter ALERTING (B1/B8/B9 apply only to CRITICAL), so there is no new re-fire or 30 s repeat behaviour for them.~~ **Correction (Review B-HIGH-1):** a ROC humidity-rise `water_leak` can be CRITICAL and enter ALERTING; it now follows the D7 schedule (default Standard ladder), not a flat 30 s. **Correction (Review B-MED-1):** the DND and per-recipient mute bypass apply only at severity HIGH and above; MEDIUM/LOW water_leak, freeze_risk and CO readings follow quiet hours and mutes. The extras-knob union (`_nm_cycle_a.py:200-220`) extends the same classification to operator-added tokens. **This is the intended life-safety contract.**

**Build test anchor for the repeat-phase flip:** T6 (see §5 D3) — RED on develop.

### D2 — Make `is_hazard_active` hold-aware (post-ACK gate ONLY)

**File / line:** `custom_components/universal_room_automation/domain_coordinators/safety.py:3398-3410`.

Reference implementation (unchanged from Rev 3):

```python
def is_hazard_active(self, hazard_type: str, location: str) -> bool:
    """SAFETY-NM-REFIRE-UNWIRED-1: hold-aware — a key whose clear hold
    is pending (all contributors recovered, 300 s HAZARD_MIN_HOLD_S not
    yet elapsed with no raising sensors) is reported INACTIVE so NM's
    post-ACK re-fire gate does not re-page a detector that has already
    recovered. A relapse cancels the hold (`_record_sensor_relapse` /
    `_respond_to_hazard` with `had_pending_clear`), which re-exposes
    the key here.

    Scope: this predicate is consumed ONLY by NM's post-ACK re-fire
    gate (`notification_manager.py:3034-3039`). The unacked REPEATING
    loop does NOT consult Safety-side state — life-safety doctrine is
    latch-until-ack (operator ruling 2026-10-15; see PLANNING_safety_
    nm_refire.md §0 for the D5 withdrawal evidence).
    """
    exact = f"{hazard_type}:{location}"
    for active_key in self._active_hazards:
        base = active_key[:-4] if active_key.endswith(":roc") else active_key
        if base != exact:
            continue
        # Hold-aware: a pending clear with no raising contributors == inactive.
        if (
            active_key in self._hazard_clear_pending
            and not self._hazard_raising_sensors.get(active_key)
        ):
            continue
        return True
    return False
```

Preserves the ROC-suffix behaviour shipped in SAFETY-HAZARD-NEVER-CLEARS-1 §4-G. Covered by existing test `test_safety_hazard_clear_on_recovery.py:515-525` (regression guard).

**Pre-existing gap acknowledged (see §0b):** D2 returns False after an HA restart with a still-ON detector that emitted no state-change event, because `_active_hazards` repopulates only on state-change events. This is identical to develop's post-ACK behaviour (develop returns False because `hazard_type` is empty). D1+D2 does not regress. Carded as `SAFETY-NO-INITIAL-SENSOR-PASS-1`; not fixed here.

### D3 — Tests (quality/tests/safety/ and quality/tests/notification_manager/)

**7 tests total.** Each is explicitly classified as (R) regression guard (passes on develop today) or (F) fix-proving (fails on develop today, passes on build). The RED-on-develop subset is the discriminator — reviewers must verify each by running against develop before applying the patch.

| # | Name | File | Class | Mutation anchor |
|---|---|---|---|---|
| T1 | `test_safety_notification_action_carries_hazard_type_location` | `quality/tests/safety/` | **F** | Remove either `hazard_type=` or `location=` kwarg from D1 → assertion flips. Observable: `action.hazard_type == "smoke"` and `action.location == <room>`. |
| T2 | `test_safety_is_hazard_active_true_when_active` | `quality/tests/safety/` | **R** | Covers D2 non-regression on the already-shipped path (key present, no clear pending → True). |
| T3 | `test_safety_is_hazard_active_false_when_cleared` | `quality/tests/safety/` | **R** | Covers D2 non-regression on the cleared path (key absent from `_active_hazards` → False). |
| T4 | `test_safety_is_hazard_active_false_during_clear_hold` | `quality/tests/safety/` | **F** | Revert the D2 hold-aware branch → test fails (pending-clear key with empty raising-sensors returns True on develop; D2 makes it False). |
| T5 | `test_safety_is_hazard_active_true_on_relapse_during_hold` | `quality/tests/safety/` | **R** | Drives relapse through `_respond_to_hazard` (smoke binary-sensor flips back on) exercising `had_pending_clear` + `_LIFE_SAFETY_REARM_TYPES` at `safety.py:2487-2492`. Returns True after relapse (hold cancelled). |
| T6 | `test_safety_smoke_repeat_phase_is_life_safety` | `quality/tests/notification_manager/` | **F** | **D1 blast-radius anchor.** Construct a smoke CRITICAL via `_respond_to_hazard`, drive to `REPEATING`; assert `nm._repeat_phase() == "life_safety"` AND `nm._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_LIFE_SAFETY` (30 s). RED on develop (`hazard_type=None` → returns `"phase1"` / 300 s). Mutation anchor: remove D1 kwarg → test fails. |
| T7 | `test_nm_re_evaluates_safety_hazard_round_trip` | `quality/tests/notification_manager/` | **F** | **Post-ACK round-trip.** Steps: (1) raise smoke via `_respond_to_hazard` → ALERTING; (2) `nm.async_acknowledge(...)`; (3) advance 120 s cooldown; (4) assert exactly ONE `async_notify(severity=CRITICAL)` call originating from `_re_evaluate_hazard`, counted with a PASS-THROUGH spy (`patch.object(nm, 'async_notify', wraps=nm.async_notify)`) so the real method still runs and writes rows; the fixture MUST enable at least one channel (else no rows are written and step 6 proves nothing); (5) assert the call used `hazard_type="smoke"` and `location="<room>"` (not `("", "")`); (6) assert a corresponding new `notification_log` row (written per delivered channel at `:1678-1899`) with the same `hazard_type`/`location` and later `timestamp` than the ACK row. RED on develop (hazard_type empty → is_hazard_active returns False → zero re-fires). Mutation anchor: remove D1 kwarg OR revert D2 → test fails for the right reason (post-ACK path). Note: `_re_evaluate_hazard` re-entering ALERTING restarts the REPEATING loop; T7 counts ONLY the `_re_evaluate_hazard`-originated call, not subsequent repeat ticks. |
| T7-neg | `test_nm_re_evaluate_no_refire_during_pending_clear` | `quality/tests/notification_manager/` | **R / intermediate anchor** | Negative twin of T7. Steps (1)-(2) as T7; smoke sensor recovers at t=60 s so `_hazard_clear_pending[key]` is set and `_hazard_raising_sensors[key]` is empty; advance to t=130 s (cooldown expired, hold still running); assert ZERO `_re_evaluate_hazard`-originated `async_notify` calls and `_alert_state == IDLE`. **Classification (N5):** passes on develop (empty `hazard_type` → `is_hazard_active("","")` returns False → zero re-fires). RED only on a D1-without-D2 intermediate (smoke `hazard_type` set but `is_hazard_active` not hold-aware → re-fires through the pending-clear hold). Mutation anchor: apply D1 but revert D2 → test fails. Keeps D2 honest while D1 lands. |
| T9 | `test_safety_flooding_location_is_deterministic` | `quality/tests/safety/` | **F** | **D6 anchor (F7 fix, R7 upgrade, N7 real-call-site requirement).** Spawn two subprocess runs with `PYTHONHASHSEED=0` and `PYTHONHASHSEED=1`. Each subprocess: (i) imports `SafetyCoordinator`; (ii) builds an instance via `SafetyCoordinator.__new__(SafetyCoordinator)` and sets `_active_leak_sensors`, `_sensor_locations`, `_leak_start_times` to drive `_check_flooding_escalation` into its multi-leak branch with `["Kitchen", "Garage"]` as the leaking locations; (iii) calls the **real** `_check_flooding_escalation` (NOT a copy of the `", ".join(...)` expression — hollow anchors are forbidden); (iv) prints the resulting `Hazard.location`. The parent test asserts both subprocess outputs equal `"Garage, Kitchen"` AND `== ", ".join(sorted(set(["Kitchen", "Garage"])))`. Mutation anchor: revert D6 (`sorted` → bare `set`) → at least one of the two seeded subprocess runs produces `"Kitchen, Garage"` → test fails. |

**RED-on-develop subset (reviewer verification required):** T1, T4, T6, T7, T9. (5 fix-proving.)
**R / regression guards (GREEN on develop):** T2, T3, T5, T7-neg. (4; T7-neg is R-with-intermediate-anchor — RED on D1-without-D2.)
**Total:** 7 tests. (Rev 3's 14 tests included T8, T8-fail-open, T10, T11a, T11b for D5 — all removed with D5.)

### D4 — Doc updates (same commit as build, per CLAUDE.md §10 rule)

- `docs/Coordinator/SAFETY_COORDINATOR.md` §5: add a paragraph covering (a) `is_hazard_active` hold-aware post-ACK gate (how pending-clear + empty raising-sensors is reported INACTIVE, how a relapse via `_respond_to_hazard` re-exposes the key); (b) the deliberate asymmetry — **the unacked REPEATING loop does not consult Safety-side state** and will latch-until-ack at the 30 s life-safety cadence (life-safety doctrine; see §5 D5 withdrawal in the planning doc for evidence); (c) the pre-existing gap: Safety has no initial sensor-state pass, so a still-ON detector after an HA restart cannot be re-fired through the post-ACK gate until a state-change event re-populates `_active_hazards` (carded as `SAFETY-NO-INITIAL-SENSOR-PASS-1`).
- `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` §10: mark the SAFETY-NM-REFIRE-UNWIRED fold-out as "shipped v<next>" with back-link, noting the D5 scope was deferred.

### ~~D5 — Stop the unacked repeat loop when the hazard key has LEFT Safety's `_active_hazards`~~

**WITHDRAWN** — see §0 (full evidence, revival trigger, carded follow-ups). The unacked REPEATING path is not modified in this cycle. `notification_manager.py:2645-2710` (`_repeat_alert`) is byte-identical to develop post-build.

### D6 — Deterministic flooding location (F7, R7, N7)

**File / line:** `custom_components/universal_room_automation/domain_coordinators/safety.py:1919, 1926`.

**Change:**

```python
# before:
location=", ".join(set(locations)),
...
f"{', '.join(set(locations))}!"

# after:
location=", ".join(sorted(set(locations))),
...
f"{', '.join(sorted(set(locations)))}!"
```

**Rationale:** `set()` iteration order is non-deterministic across process restarts (hash randomisation) so a flooding hazard raised, cleared partway, then re-keyed may not match itself in `_active_hazards` → `is_hazard_active` returns False on a still-active multi-sensor flood at post-ACK re-fire. One-line, in-cycle per Fix LOWs In-Cycle. T9 is the anchor (dual `PYTHONHASHSEED` subprocess run driving the real `_check_flooding_escalation` per N7).

## 6. Non-goals

- No change to NM cooldown defaults (`DEFAULT_NM_COOLDOWN_SMOKE=2` etc.).
- No change to the life-safety hazard set (`NM_LIFE_SAFETY_HAZARDS`).
- No new `NotificationAction` emission sites, no new DAO, no schema change.
- No change to `BaseCoordinator`. No new predicate on `SafetyCoordinator`.
- **No touch to `_repeat_alert` in NM.** The unacked REPEATING loop is byte-identical to develop post-build; latch-until-ack is the shipped semantics. See §0 for the D5 withdrawal evidence.
- No readiness flag on Safety (`_initial_evaluation_complete` withdrawn with D5). The underlying "no initial sensor-state pass" gap is carded as `SAFETY-NO-INITIAL-SENSOR-PASS-1` — not fixed here.
- No fix to NM's single-slot `_active_alert_data` (`notification_manager.py:2515-2600`). Pre-existing limitation on the post-ACK path too (two concurrent CRITICALs: the earlier one's cooldown re-fire would key off the latest slot's data). Carded as `NM-MULTI-ALERT-TRACKING-1`.
- No behaviour change for non-life-safety Safety hazards at the ALERTING / cooldown / repeat machinery (they never enter ALERTING). D1 only affects their boot-settle, DND, mute, and token-bucket classification — INTENDED (R3).
- Not re-opening SAFETY-HAZARD-NEVER-CLEARS-1 — treat its machinery (`_hazard_clear_pending`, `_sweep_hazard_clears`, `HAZARD_MIN_HOLD_S`, `_record_sensor_recovery/_relapse`) as a stable primitive to be read.
- **Not fixing** `security.py:825-828` (`"intrusion"` vs `"intruder"` token mismatch — F4). Separately carded as `SECURITY-REFIRE-INTRUSION-KEY-1`.

## 7. Knobs on the ladder

Rule: "Numbers get knobs". New numbers introduced here: **none**. Reused numbers and their rung:

| Number | Rung | Home | Why |
|---|---|---|---|
| `HAZARD_MIN_HOLD_S = 300` | 1 (module const in `safety.py`) | shipped v5.103.61 | Safety-semantics bound. |
| `DEFAULT_NM_COOLDOWN_SMOKE/_CO = 2 min` | 2 (options flow) | `const.py` COOLDOWN_CONFIG | Operator-tunable paging cadence. |
| `DEFAULT_NM_COOLDOWN_FLOODING = 5 min` | 2 (options flow) | `const.py` COOLDOWN_CONFIG | Operator-tunable. |
| `NM_REPEAT_INTERVAL_LIFE_SAFETY = 30 s` | 1 (module const) | `const.py:3387` | Safety contract. Operator-visible: unacked life-safety alerts repeat at 30 s post-D1 (vs 300 s decay ladder on develop); if "unacked repeat fatigue" surfaces, promote to Rung 2 via `SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1` (carded) — do NOT reintroduce D5. |

No new readiness flag, no new predicate. Rev 3 proposed `Safety._initial_evaluation_complete` (Rung 1) and `Safety.is_hazard_key_present` — both withdrawn with D5.

## 8. Acceptance criteria

Real `notification_log` columns (`database.py:4440-4490`): `id, timestamp, coordinator_id, severity, title, message, hazard_type, location, person_id, channel, delivered, acknowledged, ack_time, cooldown_expires, dry_run, recipient_id, route_reason, dnd_bypass_applied, bucket_outcome, matrix_branch`.

### D1 — hazard_type+location on NotificationAction
- **Verify (unit):** T1, T6.
- **Verify (DB row):** latest `notification_log` row for `coordinator_id='safety'` has `hazard_type` and `location` non-NULL.
- **Live (DB, post-deploy):**
  ```sql
  SELECT id, timestamp, coordinator_id, hazard_type, location, severity
    FROM notification_log
   WHERE coordinator_id='safety'
     AND timestamp > datetime('now','-1 day')
   ORDER BY id DESC
   LIMIT 20;
  ```
  Zero rows with `hazard_type IS NULL OR hazard_type=''`.

### D2 — is_hazard_active hold-aware (post-ACK gate ONLY)
- **Verify (unit):** T2, T3, T4, T5, T7, T7-neg.
- **Live (DB)** — N6 SQL fix (`severity='CRITICAL'` uppercase; `database.py:4647` filter + `notification_manager.py:1633` write use `severity.name`):
  ```sql
  SELECT id, timestamp, hazard_type, location, acknowledged, ack_time,
         cooldown_expires
    FROM notification_log
   WHERE coordinator_id='safety' AND severity='CRITICAL'
     AND timestamp > datetime('now','-1 day')
   ORDER BY id DESC;
  ```
  Expect: for a real still-active ACK'd life-safety event, a re-fire row with the same `hazard_type` + `location` and a `timestamp` ≈ `ack_time + cooldown` (120 s smoke/CO, 300 s flooding). Zero re-fire rows whose `hazard_type` was in `_hazard_clear_pending` with no raising sensors at the time of cooldown expiry.

### D6 — deterministic flooding location
- **Verify (unit):** T9 (dual `PYTHONHASHSEED` subprocess run driving the real `_check_flooding_escalation` per N7).
- **Live:** on any multi-sensor flood, the `notification_log.location` column alphabetises the room names (operator-visible via dashboard + DB).

### D3 — tests
- **Test:** all 7 functions PASS on build. Per-test mutation anchors in §5 D3.
- **RED-on-develop subset (reviewer must verify before applying patch):** T1, T4, T6, T7, T9. (5.)
- **Regression guards (GREEN on develop):** T2, T3, T5, T7-neg. (4; T7-neg is R-with-intermediate-anchor — RED on D1-without-D2.)

### Latch-until-ack (unacked path, documentation only)
- **Live (observational, NOT a regression check):** an unacked CRITICAL smoke / CO / flooding `notification_log` cluster shows rows at ~30 s cadence (`NM_REPEAT_INTERVAL_LIFE_SAFETY`) continuing until a human ACK event. This is **intended**. No auto-terminal row is written by D5 (withdrawn). The absence of auto-clear is the contract, not a defect.

## 9. Review framings (Tier 2-DB, three framing-disjoint reviews)

- **A — data integrity + payload shape.** Every `NotificationAction` emission site in `safety.py` still well-formed post-D1? `notification_log` row shape unchanged (D1 adds no columns, D6 only changes a string value)? Any `Hazard` construction site missing `location` (would crash)? D6's `sorted(...)` round-trips through the DB cleanly? No audit-row shape changes (D5 withdrawn removes the `[AUTO-CLEAR]` audit row from scope).
- **B — migration correctness + signal chain integrity (post-ACK path only).** Full trace from `_respond_to_hazard` → `manager.py:1070` → `NM.async_notify` → `_enter_alerting` → (post-ACK) `async_acknowledge` → `_start_cooldown` → `_cooldown_expired` → `_re_evaluate_hazard` → `is_hazard_active(hazard_type, location)` → either re-fire or IDLE. Does the smoke/CO 2 min cooldown + 5 min flooding cooldown interact correctly with the 300 s clear hold at every reachable state (active, recovering mid-cooldown, relapsing mid-cooldown with `had_pending_clear`, cleared before cooldown fires)? Enumerate every `is_hazard_active` reader (`grep -n 'is_hazard_active' custom_components/`) and confirm NM `:3034-3039` is the sole consumer. Confirm the unacked REPEATING loop (`_repeat_alert`) is byte-identical to develop (no D5 residue). Confirm **non-regression vs develop** for the restart-with-still-ON-detector case (both develop and D1+D2 fail to re-fire — identical outcome, documented in §0b; the carded `SAFETY-NO-INITIAL-SENSOR-PASS-1` is NOT a regression and MUST NOT be fixed in this cycle).
- **C — new surfaces + test fixture authority.** Mutation-anchor every test in D3: delete the `hazard_type=` kwarg → T1 and T6 fail; revert D2 hold-aware branch → T4 fails; apply D1 but revert D2 → T7-neg fails (intermediate anchor); drop D1 OR revert D2 → T7 fails (via two different failure modes — verify the test diagnostic distinguishes); revert D6 sorted → T9 fails under at least one `PYTHONHASHSEED`. **N7 real-call-site requirement:** T9's subprocess MUST drive `_check_flooding_escalation` (the production method) and MUST NOT embed a copy of the `", ".join(...)` expression. Verify by reading T9's source. **N3 observable requirement:** T7's "re-fire count" assertion counts invocations of `async_notify` from the `_re_evaluate_hazard` call site (`notification_manager.py:3046-3054`), NOT `_repeat_alert` ticks (which write no `notification_log` row). The per-channel `notification_log` rows (`:1678-1899`, written only when a channel is enabled; the spy must be pass-through `wraps=`) are the canonical downstream observable.

**Life-safety discriminator (post-deploy):** the `notification_log` DB row (uppercase `severity='CRITICAL'`) is the authoritative signal, not the log string. A sentinels-only log = payload-shape failure.

## 10. Open questions

1. **Pending-clear discriminator ambiguity (resolved).** D2 reports both "already cleared (key popped)" and "pending-clear hold running with empty raising sensors" as `is_hazard_active == False`. Operator-facing consequence on the ACK path: during the 300 s pending-clear window the NM post-ACK re-fire gate sees "cleared" while the dashboard safety-alert entity may still read ON (deliberate, orchestrator ruling 2026-10-15 Q1).
2. ~~Non-life-safety re-fire.~~ **Withdrawn** (F1).
3. **`fire` and `intruder` not emitted by Safety.** Reference only; `intruder` carded under `SECURITY-REFIRE-INTRUSION-KEY-1`; `fire` emission is not currently reachable.
4. **Unacked repeat cadence (operator-visible change, documented not open).** 300 s decay ladder → 30 s fixed post-D1. Carded cadence knob: `SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1` (Rung-2 options-flow promotion of `NM_REPEAT_INTERVAL_LIFE_SAFETY`). Not this cycle.
5. **Still-ON-after-restart post-ACK silence.** Pre-existing, non-regression (§0b). Carded: `SAFETY-NO-INITIAL-SENSOR-PASS-1`.
6. **NM single alert slot blind spot on `_re_evaluate_hazard`.** Pre-existing. Carded: `NM-MULTI-ALERT-TRACKING-1`. Also the D5-revival precondition.

## 11. Orchestrator rulings on open questions

- **Q1 (2026-10-15):** YES. While a hazard's clear hold is pending on the ACK path, the dashboard may read ON for up to 300 s while the NM post-ACK re-fire gate reads cleared.
- **Q2 (Rev 2 revision, 2026-10-15):** no change to NM's re-fire policy for non-CRITICAL hazards (they never reach ALERTING).
- **Q3 (2026-10-15):** carded as `SECURITY-REFIRE-INTRUSION-KEY-1`.
- **R1 / R2 / N1 / N2 / N4 (Rev 4, 2026-10-15):** D5 WITHDRAWN. Latch-until-ack is the correct life-safety semantics. All D5 supporting mechanisms (`is_hazard_key_present`, `_initial_evaluation_complete`, R4 teardown block, all four fail-open guards) are removed. Revival trigger: operator reports unacked-repeat fatigue AND Safety gains an initial sensor-state pass (`SAFETY-NO-INITIAL-SENSOR-PASS-1`) AND NM gains multi-alert tracking (`NM-MULTI-ALERT-TRACKING-1`). Minimal operator relief in the interim is the cadence knob (`SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1`), NOT a re-attempt at stop-on-clear.
- **R3 (Rev 3, carried):** `water_leak` / `freeze_risk` in `NM_LIFE_SAFETY_HAZARDS` is deliberate; D1's DND/mute/token-bucket bypass for their HIGH alerts is INTENDED. The repeat-path bypass site at `:2700` recorded as B9.
- **R4 (Rev 3, moot):** D5 withdrawn — teardown block removed.
- **R5 (Rev 4):** test classification fixed. T7-neg re-classed R / intermediate anchor. D5 tests (T8, T8-fail-open, T10, T11a, T11b) removed. Final count 7.
- **R6 (Rev 4):** D5 live timing section removed with D5 withdrawal; D2 live SQL case corrected to `'CRITICAL'` (N6).
- **R7 / N7 (Rev 4):** T9 upgraded to drive the real `_check_flooding_escalation` under dual `PYTHONHASHSEED` subprocess invocations; hollow-anchor copies of the join expression are forbidden.
- **N3 (Rev 4):** test observables corrected. T7 counts `_re_evaluate_hazard`-originated `async_notify` calls and asserts the per-channel `notification_log` row (`:1678-1899`) via a pass-through spy with a channel enabled (Rev 4.1 S2). No test asserts on repeat-tick `notification_log` rows (none are written).

---

### Rev 4 changelog
- §0 NEW: full "Withdrawn: D5" evidence section with R1 / R2 / N1 / N1c / N2 / N3 / N4 reachable repros, marginal-benefit decomposition, revival trigger, and companion cards (`SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1`, `SAFETY-NO-INITIAL-SENSOR-PASS-1`, `NM-MULTI-ALERT-TRACKING-1`).
- §0a NEW: Rev 3 → Rev 4 resolution table for N1-N7.
- §0b NEW: honest "post-ACK gate × no-initial-sensor-pass" comparison — D1+D2 is NOT a regression vs develop on the restart-with-still-ON case; both fail to re-fire; carded as `SAFETY-NO-INITIAL-SENSOR-PASS-1` and not fixed here.
- §1 invariant rewritten: covers post-ACK path only (D1+D2); clause 4 restated as "latch-until-ack is the unacked contract, not a predicate".
- §2 institutional context updated: `is_hazard_key_present` and `_initial_evaluation_complete` entries marked WITHDRAWN; `_hazard_raising_sensors` added as D2 dependency; `_repeat_alert` moved from "D5 target" to "not touched this cycle".
- §4 consumer map: `_repeat_alert` struck from consumer list.
- §5 D1: carried from Rev 3 unchanged (nine-row blast-radius table incl. B9); row B1 commentary updated to point at cadence-knob card instead of D5.
- §5 D2: docstring updated to document the latch-until-ack asymmetry and the pre-existing `_active_hazards` priming gap.
- §5 D3 rewritten: 7 tests (not 14); T8 / T8-fail-open / T10 / T11a / T11b removed with D5; T7-neg re-classed R / intermediate anchor per N5; T9 updated per N7 to drive real `_check_flooding_escalation` under dual PYTHONHASHSEED.
- §5 D5: replaced with "WITHDRAWN" pointer to §0.
- §5 D6: unchanged behaviour, N7 real-call-site requirement folded into T9 reference.
- §6 non-goals updated: `_repeat_alert` explicitly byte-identical; no readiness flag; no new predicate; NM single-slot not fixed.
- §7 knob ladder: no new numbers; readiness flag entry removed; added cadence-knob future-work pointer on `NM_REPEAT_INTERVAL_LIFE_SAFETY`.
- §8 acceptance criteria: D5 section removed; D2 live SQL case fixed to `'CRITICAL'` (N6); latch-until-ack documented as observational, not a regression check.
- §9 review framings rewritten: predicate split removed; non-regression-vs-develop check added for the restart-still-ON case; N3 observable requirement + N7 real-call-site requirement called out.
- §10 open questions: added items 4-6 (cadence knob, no-initial-sensor-pass, NM single-slot) as carded companions.
- §11 rulings extended with the D5 withdrawal and R5-R7 / N3 / N6 / N7 Rev 4 resolutions.


## Rev 4.1 (2026-10-15, orchestrator) — Rev 4 re-review S1/S2
- **S2:** the `notification_log` row source corrected throughout (rows are per delivered channel at `notification_manager.py:1678-1899`; `:551` is dry-run-only). T7 uses a pass-through spy and enables a channel.
- **S1:** blast-radius rows B10 (alert-light patterns) and B11 (TTS overnight DND bypass) added, both intended.
- **Deploy timing (reviewer advisory, adopted):** after D1 an unacked smoke/CO/flood alert pages every 30 s through DND/mute with speakers and lights until acked (develop: 300 s decaying). Correct for a real event but much louder on a false trip. Build and review now; **hold deploy until the operator is home (Sun 10-18)** or until Jaya has been shown how to acknowledge, whichever the operator picks.

## Rev 4.2 (2026-10-15, operator rulings) — life-safety repeat schedule becomes a setting
Operator: "A. but should this be a setting ie timing. it feels like it should with a default." and deploy "Sunday" (hold until 10-18).

**D7 (NEW deliverable, absorbs card SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1):** a Coordinator-Manager options-flow select `CONF_NM_LIFE_SAFETY_REPEAT_SCHEDULE` (rung 2: operator-settable, persistent, infrequent), on the NM step next to the quiet-hours fields, as a named-bucket dropdown per the label style guide:
- `standard` (**default**): "Standard: every 5 min for the first hour, then every 30 min, then daily". Same ladder as non-life-safety CRITICALs (`NM_REPEAT_PHASE1_S` / `PHASE1_WINDOW_S` / `PHASE2_S` / `DAILY_AFTER_S`). This is today's effective behaviour for Safety alerts.
- `fast_start`: "Fast start: every minute for the first 10 minutes, then Standard".
- `urgent`: "Urgent: every 30 s until acknowledged" (the old `NM_REPEAT_INTERVAL_LIFE_SAFETY`).

Single consumer site: `notification_manager.py:_repeat_interval_for_active_alert` (~2562-2588), life-safety branch; plus `_repeat_phase` (~2621) diagnostics labels must reflect the chosen schedule. New fast-start numbers are rung-1 constants (`NM_REPEAT_FAST_START_S = 60`, `NM_REPEAT_FAST_START_WINDOW_S = 600`). Unknown/missing value -> `standard` (default). Read through the existing `_refresh_config()` path, so a change takes effect on the next repeat tick without a reload.

**Builder must first enumerate every hazard type that is life-safety today** (base `NM_LIFE_SAFETY_HAZARDS` + extras knob) and every producer currently emitting one (Security? leak paths?). Changing the default from 30 s to Standard changes those producers' repeat cadence too. Record the list; if any non-Safety producer relies on 30 s today, report it to the orchestrator before shipping (operator decision).

Tests (F = fail on develop): the default schedule yields 300 s at age 0, 1800 s at age 3601 s, 86400 s after 24 h for a smoke alert; fast_start yields 60 s at age 0 and 300 s at age 601 s; urgent yields 30 s; unknown value -> standard; options round-trip (save/reload shows the selection); `_repeat_phase` labels. Mutation anchors on the life-safety branch.

Blast radius row B1 is updated: the unacked repeat for smoke/CO/flooding stays on today's decaying ladder by default (NOT 30 s flat). Deploy is held until Sun 10-18 regardless.

## Rev 4.3 (2026-10-15, orchestrator rulings on Reviews A/B)
- **B-HIGH-1:** `water_leak` and `freeze_risk` join `NM_SCHEDULED_LIFE_SAFETY_HAZARDS`; §2 / R3 / B1 corrected above.
- **B-MED-1:** the life-safety DND floor (`_recipient_bypasses_dnd`) and the router mute bypass require severity >= HIGH. The token-bucket bypass was already CRITICAL-only.
- **B-MED-2:** `nm_life_safety_repeat_schedule` joins `_NM_C_KEYS` (so `OPTIONS_RELOAD_SUPPRESS_KEYS` and `_NO_LIVE_ATTR_KEYS`). `_apply_in_place` calls `NotificationManager.reschedule_repeat_for_config_change()`, which re-arms the pending repeat of an active alert with the new interval.
- **B-LOW-1 / A1 / A2 / A3:** the extras-knob description notes Safety alerts; the dropdown labels are translated via the strings `selector` block; the `_repeat_phase` docstring lists fast_start; the help text says intruder and promoted extras stay at 30 s.
