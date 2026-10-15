# PLANNING — SAFETY-NM-REFIRE-UNWIRED-1 (Rev 3): wire hazard_type/location on the Safety NotificationAction, make `is_hazard_active` hold-aware (post-ACK gate only), and stop the unacked repeat loop when the hazard key has LEFT Safety's `_active_hazards`

- Card: `SAFETY-NM-REFIRE-UNWIRED-1`
- Blocker: `SAFETY-HAZARD-NEVER-CLEARS-1` — shipped v5.103.61 (2026-10-15, live).
- Tier: **Tier 2-DB** (standing policy for regression-prone life-safety work; cross-coordinator safety ↔ NM; touches a shared primitive — the NM re-fire / repeat path — consumed by every coordinator).
- Branch / worktree: `plan/safety-refire` under `.claude/worktrees/plan-safety-refire`.
- Scope: **plan only**. Do not build; do not run the full suite.
- Rev 3 motivation: Rev 2 re-review (`docs/reviews/code-review/plan_safety_nm_refire_review.md` §"Rev 2 re-review", 2026-10-15, FIX-REQUIRED) returned R1-R7. This revision resolves each under the orchestrator rulings dated 2026-10-15:
  - **R1 (HIGH):** D5 MUST NOT use the hold-aware predicate. It stops repeating only once the hazard key has LEFT `_active_hazards` (i.e. after the clear hold has elapsed and the per-minute sweep has popped the key). We introduce a new, dedicated, non-hold-aware predicate `is_hazard_key_present(hazard_type, location)`. D2's hold-aware `is_hazard_active` remains the post-ACK re-fire gate ONLY.
  - **R2 (HIGH):** D5 fails OPEN (keep paging) when `hazard_type`/`location` is empty, when Safety is not yet loaded, and during a boot grace until Safety has evaluated its sensors at least once (NEW readiness flag `_initial_evaluation_complete` — no equivalent exists today; justified below).
  - **R3 (MEDIUM):** state plainly that `water_leak` and `freeze_risk` being in `NM_LIFE_SAFETY_HAZARDS` is deliberate; their HIGH alerts starting to bypass DND/mute/token-bucket after D1 is INTENDED. Add the missing `:2700` repeat-path bypass row.
  - **R4 (MEDIUM):** D5's terminal transition performs the SAME teardown as the normal ack path — cancel repeat unsub, cancel `_light_pattern_task`, `_restore_alert_lights()`, and mark the DB row resolved by REUSING `database.acknowledge_notification()` (there is no non-ack resolution path; justification + alternative-considered below).
  - **R5/R6/R7:** test classification + count fixed; RED-first tests added for R1 and R2; R4 teardown asserts added to T8; T9 forces a non-trivial order (dual `PYTHONHASHSEED` subprocess runs); D5 live timing corrected to **~30 s after hold expiry (~5.5 min after recovery)**.

## 0. Review-resolution table (Rev 2 re-review → Rev 3)

| # | Severity | Finding | Resolution in Rev 3 | Verified against |
|---|---|---|---|---|
| R1 | HIGH | D5 using the hold-aware predicate silences a relapsed smoke/CO: smoke ON t=0 (page, dedup stamped), OFF t=5, repeat tick t=30 (hold pending, hold-aware returns False) → IDLE; relapse ON t=40 inside AlertDeduplicator 60 s window → `should_alert=False` → no page. NM is IDLE, detector is ON, nothing re-pages. | **D5 redesigned** to use a NEW, non-hold-aware predicate `Safety.is_hazard_key_present(hazard_type, location)` that returns `True` iff the base key (stripping any `:roc` suffix) is in `_active_hazards`, regardless of `_hazard_clear_pending`. D5 drops to IDLE only after the per-minute sweep (`_sweep_hazard_clears`) pops the key at the 300 s hold expiry. R1 repro walk: t=0 ON (page, dedup stamp 0); t=5 OFF (hold armed, key still in `_active_hazards`, `_hazard_clear_pending` set); t=30 repeat tick → key present → **keep paging** (page row written at t=30, dedup stamp refreshed at t=30); t=40 relapse through `_respond_to_hazard` cancels pending clear (`had_pending_clear` branch at `safety.py:2487-2492`) — now `is_hazard_key_present=True` and `is_hazard_active=True` — the subsequent 30 s repeat ticks continue paging. The 60 s AlertDeduplicator window is irrelevant: paging never stopped, so there is no "silent" interval. Hold expiry still arrives at t≈340-360 s AFTER THE LAST RAISING SENSOR GOES OFF; if the detector is still chattering, the hold is never armed to completion. D2's hold-aware `is_hazard_active` remains the post-ACK gate ONLY (`_re_evaluate_hazard` at `notification_manager.py:3034-3039`); D5 does not call it. | `safety.py:3398-3410` (D2 predicate — unchanged scope); `safety.py:1037, 2493, 2882, 2924, 2944, 2969, 3048` (`_active_hazards` membership — pop sites); `safety.py:2900-2954` (`_sweep_hazard_clears` pops key at hold expiry); `safety.py:2487-2492` (`had_pending_clear` + `_LIFE_SAFETY_REARM_TYPES`); `safety.py:935, 961` (AlertDeduplicator CRITICAL window 60 s, stamped only on `should_alert=True`); `notification_manager.py:2645-2710` (D5 target). |
| R2 | HIGH | D5 fail-closed on empty key and on the boot race: `_recover_state_from_db` (`notification_manager.py:4895-4913`) restores REPEATING with `hazard_type`/`location` from the DB row; pre-D1 rows have NULL `hazard_type`; `is_hazard_key_present("", "")` returns False → D5 silences a still-active pre-deploy alert on the first tick. Also: safety's `_active_hazards` repopulates only after sensor evaluation runs; a 30 s repeat tick firing before Safety has evaluated sees an empty dict → False → IDLE. | **D5 fail-open guards (explicit discharges):** (i) If `hazard_type == ""` OR `location == ""` after `.get(..., "") or ""` normalization → fail-open (keep paging). *Discharge:* post-deploy, D1 ensures every new row carries non-empty values; pre-D1 recovered rows age out naturally (ack path or sensor-side clear). (ii) If the coordinator-manager key is absent in `hass.data[DOMAIN]`, or `cm.coordinators.get("safety")` returns `None` → fail-open. *Discharge:* only reachable during setup teardown windows; the repeat tick listener is cancelled on NM unload. (iii) If `coord.is_hazard_key_present` raises → fail-open. (iv) **Boot grace:** if Safety has not completed its initial sensor evaluation (`coord._initial_evaluation_complete is False`) → fail-open. **NEW readiness flag** `Safety._initial_evaluation_complete: bool`, initialised `False` in `__init__` and set `True` at the end of the first `_async_periodic_check` invocation (which runs on a 1-min interval scheduled in `async_setup` at `safety.py:1273-1276`). *Discharge:* flag flips at most ~60 s after HA start under normal conditions; while False, D5 keeps paging a live life-safety hazard — the correct conservative behaviour. No existing flag has equivalent semantics (greps for `last_update_success`, `_ready`, `_initial`, `_setup_complete`, `async_config_entry_first_refresh` in `safety.py`/`base.py` returned no match; Safety does not inherit `DataUpdateCoordinator`). Justified NEW per Institutional-Context-First. Covered by T11a / T11b. | `notification_manager.py:4895-4913` (restore shape); `safety.py:1214-1290` (setup); `safety.py:1273-1276` (periodic 1-min); `safety.py:1037` (`_active_hazards` init empty); `base.py:120-240` (BaseCoordinator — no readiness primitive). |
| R3 | MEDIUM | Rev 2 "NON-regression" paragraph wrong for `water_leak`/`freeze_risk`; also missing `:2700` repeat-path mute/DND bypass row. | §5 D1 blast-radius table **restated**: `water_leak` and `freeze_risk` are deliberately in `NM_LIFE_SAFETY_HAZARDS` (code-reviewed rung-1 list, `const.py:3391-3399`), and their HIGH alerts begin to bypass DND, per-recipient mute, and the token bucket after D1 lands. **This is INTENDED** per the life-safety contract (operator ruling 2026-10-15 R3). Row **B9 added** for `_repeat_alert` life-safety mute/DND bypass at `notification_manager.py:2700` (same class as B3/B4 but on the repeat path, computed via `is_life_safety_hazard` and consumed inside `_recipient_bypasses_dnd` / `_route_for_recipient` at `:2711-2720`). The misleading paragraph claiming "non-life-safety treatment preserved" is REMOVED. Also notes `_nm_cycle_a.py:200-220` extras-knob union: operator may add additional hazard tokens to the life-safety set via options; those tokens get the same B1-B9 treatment post-D1. | `const.py:3391-3399`; `notification_manager.py:2700, 2711-2720`; `_nm_cycle_a.py:200-220` (extras knob). |
| R4 | MEDIUM | D5's IDLE transition leaves `_light_pattern_task` running (lights flash forever) and the DB row `acknowledged=0` (could be resurrected by `get_active_critical` on next boot). | **D5 terminal cleanup REUSES the ack-path teardown** (`notification_manager.py:2886-2900`): (i) cancel `_repeat_unsub`; (ii) cancel `_light_pattern_task` and `await self._restore_alert_lights()`; (iii) call `database.acknowledge_notification()` to mark the row `acknowledged=1`. There is **no existing non-ack resolution path** (`grep -n "acknowledge_notification\\|clear_notification\\|resolve_notification" database.py` → sole hit is the ack method at `database.py:4628`); reusing the ack method is correct for the operator-facing meaning ("Safety reports hazard cleared → NM resolves the row"). The audit row distinguishes the auto-clear from a human ack via `route_reason="auto_cleared:safety_hazard_absent"` and `bucket_outcome="auto_clear"` (reuses `_emit_audit_row` at `notification_manager.py:2908-2950`, same path the ack uses). *Alternative considered:* add a sibling `database.resolve_notification(reason)` — rejected as scope creep for this cycle; `acknowledge_notification` already clears the exact row `get_active_critical` would resurrect (`database.py:4628-4660`). Covered by T8 (R4 asserts added). | `notification_manager.py:2437-2488` (`_run_light_pattern` runs until cancel), `:2886-2900` (ack teardown), `:4628` (`acknowledge_notification`), `:2908-2950` (`_emit_audit_row`); `database.py:4628-4660` (clears `acknowledged=0` rows). |
| R5 | MEDIUM | Test classification + count errors. | §5 D3 **rewritten**: 11 tests total (T1-T9, T7-neg, T8-fail-open). Classification corrected: T8-fail-open is **R / post-build mutation anchor** (passes on develop today because `_repeat_alert` never calls the predicate on develop — exercised only after D5 lands, then mutated by removing the `try/except`). Added **T10** (R1 anchor — unacked relapse inside 60 s dedup window keeps paging) and **T11a / T11b** (R2 anchors — empty `hazard_type` → fail-open; boot before `_initial_evaluation_complete=True` → fail-open). T8 extended with R4 teardown asserts (lights restored, DB row `acknowledged=1`, `_light_pattern_task is None`, `_repeat_unsub is None`). RED-on-develop subset refreshed in §8. Total test count stated correctly throughout (14 after T10/T11a/T11b additions). | `notification_manager.py:2645-2710` (predicate not called on develop); `safety.py:2487-2492` (relapse path). |
| R6 | LOW | D5 live expectation contradicted the (fixed in R1) D5 code. | §8 D5 live SQL + prose rewritten against the R1 fix: the final `notification_log` row for an unacked smoke/CO cluster arrives **~30 s after hold expiry**, which is **~5.5 min (330 s) after sensor recovery** (300 s `HAZARD_MIN_HOLD_S` + up to one 30 s repeat tick). Threshold tightened to `recovery_ts + 360 s` for regression detection. | `safety.py:3398-3410` + `safety.py` `_sweep_hazard_clears` runs on 1-min interval → hold-expiry detection takes up to 60 s past the 300 s mark. Documented in §8. |
| R7 | LOW | T9 could pass on develop because `set()` iteration of two short strings is often stable within one process. | T9 **upgraded** to run the construction under TWO distinct `PYTHONHASHSEED` subprocess invocations (0 and 1) and assert both produce `"Garage, Kitchen"`. A supplementary assertion diffs against `", ".join(sorted(set(locs)))` directly for mutation-anchoring. RED on develop under at least one of the two seeds (shown empirically in the test's docstring). | Python hash randomisation docs (`PYTHONHASHSEED` controls string hashing). |

**Carried from Rev 2 unchanged:** D1 (populate `hazard_type` + `location` on the Safety `NotificationAction`), D2 (`is_hazard_active` hold-aware), D6 (`sorted()` on flooding location), the knob-ladder table, the single-emission-site institutional-context verdict.

## 1. Falsifiable invariant (Rev 3)

> **INV-REFIRE (Rev 3)**: Let `H_safety_crit = {smoke, carbon_monoxide, flooding}` be the subset of `HazardType` the Safety Coordinator actually emits at CRITICAL severity (intersected with `const.NM_LIFE_SAFETY_HAZARDS`). For every hazard emitted by Safety with `hazard_type ∈ H_safety_crit`:
>
> 1. **Still-active ⇒ re-page, on BOTH paths.**
>    - *Post-ACK path:* when NM's cooldown expires in state `COOLDOWN`, `_re_evaluate_hazard` (`notification_manager.py:3020-3060`) MUST see `coordinator.is_hazard_active(hazard_type, location) == True` (D2, hold-aware) and MUST re-fire exactly once (one `async_notify(severity=CRITICAL)` call from `_re_evaluate_hazard`).
>    - *Unacked REPEATING path:* while `_alert_state == REPEATING` and the hazard is unacked, each `_repeat_alert` tick MUST re-page as long as `coordinator.is_hazard_key_present(hazard_type, location) == True` (D5, **NOT** hold-aware).
> 2. **Pending-clear ⇒ post-ACK does not re-page; unacked DOES keep paging.**
>    - *Post-ACK path (hold-aware):* if every raising sensor has recovered but the 300 s clear hold is still running (key in `_hazard_clear_pending`), `is_hazard_active(...) == False` and NM returns to IDLE at cooldown expiry. (`constraint_2026_10_14` on the ACK path.)
>    - *Unacked REPEATING path (key-present only):* the key is STILL in `_active_hazards` during the hold, so `is_hazard_key_present(...) == True` and the repeat loop MUST keep paging. This is deliberate: an unacked life-safety alert must not be silenced while the hazard key is retained — only after the sweep has popped it (hold elapsed) does the loop transition to IDLE.
> 3. **Cleared (hold elapsed, key popped) ⇒ unacked repeat loop transitions to IDLE and never re-pages again for that episode.** On the first `_repeat_alert` tick where `is_hazard_key_present(...) == False`, NM transitions to IDLE, cancels `_light_pattern_task`, restores alert lights, cancels `_repeat_unsub`, and marks the DB row `acknowledged=1` via `database.acknowledge_notification()` (R4 reuse). Audit row carries `route_reason="auto_cleared:safety_hazard_absent"`.
> 4. **Re-raise during pending clear ⇒ re-page.** If the hold is pending and a contributor relapses through the smoke/CO/leak sensor path (`_respond_to_hazard` → `had_pending_clear` + `_LIFE_SAFETY_REARM_TYPES` at `safety.py:2487-2492`), both paths re-page: post-ACK via `is_hazard_active=True`, unacked via continuous paging (key never left `_active_hazards`).
> 5. **Fail-open on D5 (unacked REPEATING path).** `_repeat_alert` MUST re-page (never silence a live life-safety hazard) when ANY of the following holds:
>    - `hazard_type == ""` after normalisation (R2(i)).
>    - `location == ""` after normalisation (R2(i)).
>    - `hass.data[DOMAIN]["coordinator_manager"]` is missing OR `cm.coordinators.get("safety")` is `None` (R2(ii)).
>    - `coord.is_hazard_key_present` raises (R2(iii)).
>    - `coord._initial_evaluation_complete is False` (R2(iv)) — boot grace.
>    Clause 3 (unacked IDLE transition) is CONDITIONAL on `is_hazard_key_present` returning a well-formed `False`.
>
> **Falsification observations (any one disproves the plan):**
> - Live `notification_log` row where NM cooldown expired on an active smoke/CO hazard and no re-page row followed within one tick → clause 1 (post-ACK) false.
> - A post-ACK re-page row whose `hazard_type` matches a key currently in `_hazard_clear_pending` → clause 2 (post-ACK) false.
> - A `_re_evaluate_hazard` call with `hazard_type == ""` or `location == ""` (`notification_log` DB row with NULL/empty `hazard_type`, OR the structured log line at `notification_manager.py:3042-3044`) → the D1 wiring did not land.
> - Unacked path: smoke sensor ON t=0, OFF t=5, back ON t=40 (no ack); `notification_log` shows a gap >30 s between successive re-page rows for the same `(coordinator_id, hazard_type, location)` key before `recovery_ts + 300 s` → clause 2 (unacked) false (regression; D5 silenced a live chattering hazard).
> - Unacked path: smoke sensor ON t=0, OFF (final) at `recovery_ts`, no ack; `notification_log` continues to insert rows past `recovery_ts + 360 s` → clause 3 false.
> - An induced predicate exception during the unacked path produces NO re-page row within one repeat interval → clause 5 (fail-open) false.
> - A pre-D1 restored REPEATING row (NULL `hazard_type`) results in zero re-page rows after HA restart while the sensor is still ON → clause 5(i) false.

## 2. Institutional-context verified

Grep surfaces consulted: `const.py`, `config_flow.py`, `options_flow.py`, `sensor.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`, `services.yaml`, `domain_coordinators/*.py`, `database.py`, `docs/Coordinator/*`, `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md`.

Prior-art verdicts (REUSED / NEW with file:line):

- **`NotificationAction.hazard_type` field** — REUSED (`base.py:136`).
- **`NM.async_notify(hazard_type, location)`** — REUSED (`notification_manager.py:530-558`).
- **`BaseCoordinator.is_hazard_active`** — REUSED (`base.py:237`); override at `safety.py:3398-3410`. **D2 only.**
- **`Safety.is_hazard_key_present(hazard_type, location)`** — **NEW** (added by D5). Rationale: existing `is_hazard_active` is now hold-aware (D2) and MUST remain so for the post-ACK gate. The unacked repeat path needs a key-membership predicate that ignores the hold. No existing predicate in `base.py` / `safety.py` / `security.py` provides this (greps for `is_hazard_`, `has_hazard`, `hazard_present` on `base.py`, `safety.py`, `security.py` returned only `is_hazard_active`). Semantics: returns `True` iff for some `active_key` in `self._active_hazards`, `active_key[:-4] if active_key.endswith(":roc") else active_key == f"{hazard_type}:{location}"`. No hold / clear-pending check. Added as a method on `SafetyCoordinator` only — not on `BaseCoordinator` — because the predicate is Safety-scoped (per orchestrator ruling: D5 only applies to Safety; security's analogue is deferred to `SECURITY-REFIRE-INTRUSION-KEY-1`).
- **`Safety._initial_evaluation_complete`** — **NEW** readiness flag. No existing equivalent (`last_update_success`, `async_config_entry_first_refresh`, `_ready`, `_initial_*`, `_setup_complete`, `_first_refresh` all returned no match in `safety.py` or `base.py`; Safety does not inherit `DataUpdateCoordinator`). Initialised `False` in `__init__` (`safety.py:1013-...`); flipped `True` at the end of the first invocation of `_async_periodic_check` (scheduled at 1-min interval in `async_setup`, `safety.py:1273-1276`). Rationale documented in R2.
- **`_hazard_clear_pending`** — REUSED (`safety.py:1043, 2870, 2878, 2885, 2890, 2927, 2944, 2952, 3051, 3441`). Read-only in this cycle.
- **`_active_hazards`** — REUSED (`safety.py:1037, 2493, 2882, 2924, 2944, 2969, 3048, 3057, 3077, 3085, 3109-3133, 3153, 3185, 3214-3227, 3406, 3438`). Read-only (membership check) in this cycle.
- **`_sweep_hazard_clears`** — REUSED. Runs on the 1-min periodic tick (`safety.py:1273-1276`); pops expired keys from `_active_hazards`. This is the SOLE mechanism that transitions D5's `is_hazard_key_present` from True → False for an unacked hazard — operator-visible consequence: D5's IDLE transition is scheduled within ≤60 s of `HAZARD_MIN_HOLD_S` expiry (R6 timing).
- **`HazardType` emitted at CRITICAL by Safety** — ENUMERATED via grep of `Severity.CRITICAL` inside `Hazard(` constructors in `safety.py`: `smoke` (`safety.py:1864`), `carbon_monoxide` ≥100 ppm (via `NUMERIC_THRESHOLDS`), `flooding` (`safety.py:1917-1919`, `:1938`). WATER_LEAK tops out at HIGH; FREEZE_RISK / OVERHEAT / HIGH_CO2 / HIGH_TVOC / HUMIDITY top out at HIGH or MEDIUM — none ever enter NM's ALERTING state. **FIRE** is defined in the enum but never produced in `safety.py`. This grounds the Rev 3 invariant domain.
- **`NM_LIFE_SAFETY_HAZARDS`** — REUSED (`const.py:3391-3399`). Contents: `smoke, carbon_monoxide, fire, intruder, water_leak, freeze_risk`. The `water_leak`/`freeze_risk` inclusion is deliberate (R3). Union with operator extras knob (`_nm_cycle_a.py:200-220`).
- **NM cooldown constants** — REUSED (`const.py` COOLDOWN_CONFIG): `DEFAULT_NM_COOLDOWN_SMOKE=2`, `_CO=2`, `_FLOODING=5`, `_WATER_LEAK=10`, `_FREEZE=15`. Not touched.
- **Life-safety repeat cadence** — REUSED (`NM_REPEAT_INTERVAL_LIFE_SAFETY = 30 s`, `const.py`). Not touched.
- **`is_life_safety_hazard`** — READ-ONLY. Branches used: `notification_manager.py:2578-2579` (`_repeat_interval_for_active_alert`), `:2634` (`_repeat_phase`), `:1508-1509` (boot-settle), `:4184` (DND floor), `:4235` (router mute), `:3889-3892, 3925, 4028` (token bucket bypass), `:1480` (security-image guard), `:658` (boot-settle dedup bucket key), **`:2700` (repeat-path mute/DND bypass — R3 addition)**. The nine policies that flip when D1 lands.
- **Precedent for `hazard_type`-wired NotificationAction** — REUSED. Sites that already pass `hazard_type`+`location`: `perimeter_alert.py:1529, 2968`, `zone_monitoring_tripwire.py:125`, `button.py:2373` (test), `energy_battery.py:1313, 1507, 1599, 1769, 1855`. Safety is the single outlier.
- **Existing NotificationAction site in safety** — ENUMERATED, one and only one: `safety.py:2579-2587` inside `_respond_to_hazard`. (`rg -n 'NotificationAction\(' safety.py` → single match.)
- **`_repeat_alert` (D5 target)** — REUSED (`notification_manager.py:2645+`). The coordinator-manager lookup at `:3034-3039` (used by `_re_evaluate_hazard`) is the pattern D5 mirrors.
- **Ack-path teardown (R4 reuse target)** — REUSED (`notification_manager.py:2886-2900`): `_repeat_unsub` cancel, `_light_pattern_task` cancel + `_restore_alert_lights()`, `database.acknowledge_notification()`, `_emit_audit_row` at `:2908-2950`.
- **`database.acknowledge_notification()`** — REUSED (`database.py:4628-4660`). Clears the `acknowledged=0` row that `get_active_critical` would resurrect. No non-ack resolution DAO exists; adding one is out of scope (R4 alternative-considered). The audit row's `route_reason="auto_cleared:safety_hazard_absent"` distinguishes auto-clear from human ack in analytics.

Prior planning docs consulted:
- `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` rev 4 — read §4-G (`is_hazard_active` suffix-aware), §10 (SAFETY-NM-REFIRE-UNWIRED fold-out).
- `docs/reviews/code-review/plan_safety_nm_refire_review.md` — Rev 1 review (F1-F7) + Rev 2 re-review (R1-R7, this file's trigger).

Memory bodies pulled: CLAUDE.md standing rules (No Fabrication, Config-First, Numbers-Get-Knobs, Tier-2-DB default, Fix LOWs In-Cycle, Suppression needs a discharge, Extend existing never rebuild).

Design docs read: `docs/Coordinator/SAFETY_COORDINATOR.md` §5 clear-on-recovery (line 293: `HAZARD_MIN_HOLD_S = 300` and the per-minute sweep).

Code locations surveyed end-to-end:
- `safety.py:1013-1290` (`__init__` + `async_setup`; readiness flag will initialise here)
- `safety.py:1864-1940` (CRITICAL emission sites: smoke, flooding)
- `safety.py:2465-2600` (`_respond_to_hazard` + `NotificationAction` emit; re-arm at `:2487-2492`)
- `safety.py:2860-2954` (clear-hold machinery, `_record_sensor_recovery`, `_try_clear_if_quiet`, `_sweep_hazard_clears`)
- `safety.py:3398-3410` (`is_hazard_active` — D2 hold-aware predicate; D5's new sibling `is_hazard_key_present` sits adjacent)
- `manager.py:1070-1095` (NOTIFICATION dispatch — forwards `action.hazard_type or None` and `action.location or None`)
- `notification_manager.py:520-560` (`async_notify` + cooldown entry)
- `notification_manager.py:2437-2488` (`_run_light_pattern` — R4 cancel target)
- `notification_manager.py:2515-2600` (`_enter_alerting` — only CRITICAL enters)
- `notification_manager.py:2562-2644` (`_repeat_interval_for_active_alert`, `_repeat_phase`)
- `notification_manager.py:2645-2800` (`_repeat_alert` — D5 target; `:2700` is-life-safety read for mute/DND bypass)
- `notification_manager.py:2859-2954` (`async_acknowledge` → ack-path teardown — R4 reuse target)
- `notification_manager.py:2953-3060` (`_start_cooldown` → `_cooldown_expired` → `_re_evaluate_hazard`)
- `notification_manager.py:4880-4913` (`_recover_state_from_db` REPEATING restore — R2 motivation)
- `base.py:120-240` (`NotificationAction` schema + base `is_hazard_active`)
- `const.py` COOLDOWN_CONFIG + `NM_LIFE_SAFETY_HAZARDS` + `NM_REPEAT_*`
- `_nm_cycle_a.py:200-220` (extras-knob union into life-safety set — R3)
- `database.py:4440-4490` (`log_notification` INSERT column order — F6 source)
- `database.py:4628-4660` (`acknowledge_notification` — R4 reuse target)

## 3. Config-first check

- No configuration (knob, options-flow field, HA setting, operator action) resolves this: the data to be propagated (hazard type + location) are **computed inside the emitter** and are not operator-settable. Live NM cooldown values are tunable but irrelevant to the symptom (`is_hazard_active('','')` always-False and the unacked repeat loop never consults it at all).
- Verdict: **Code change required.** Config-first checked; no knob turn substitutes.

## 4. Producer and Consumer map

**Producer** (`safety.py:2465-2587`):
- Arithmetic: `hazard.type.value` (StrEnum → canonical token) and `hazard.location` (room/zone string populated at every `Hazard(...)` construction site: `safety.py:1864, 1891, 1917, 1938, 1805, 2073, 2175, 2200, 2229, 2404, 2446`).
- Dependency health: both are already set at every `Hazard` construction site; the `@dataclass` requires both as keyword args. Flooding's `location` composition (D6 target) is the only non-deterministic string in the set.

**Consumers:**
- `manager.py:1070-1081` (trust, forwards both into NM).
- `notification_manager.py:551` (trust, log row): writes `hazard_type` + `location` into `notification_log`.
- `notification_manager.py:3029-3039` (trust, post-ACK re-fire gate): calls `coordinator.is_hazard_active(hazard_type, location)` — D2 consumer.
- `notification_manager.py:2645-2710` (trust, unacked REPEATING loop): **new consumer via D5** — calls `coordinator.is_hazard_key_present(hazard_type, location)` (NOT the hold-aware predicate).
- `notification_manager.py:2578-2579, 2634, 1508-1509, 4184, 4235, 3889-3892, 3925, 4028, 1480, 658, 2700` (policy): read `hazard_type` for life-safety classification. **R3 blast radius** — see §5 D1.
- `sensor.py:8341, 8436, 8548, 14169` (display): dashboard readouts.
- `database.py:4440-4490` (storage, `log_notification`): persists both.

## 5. Deliverables

### D1 — Populate `hazard_type` + `location` on the Safety `NotificationAction`

**File / line:** `custom_components/universal_room_automation/domain_coordinators/safety.py:2579-2587`

**Change (surgical):** inside the one `NotificationAction(...)` constructor, add two keyword arguments:

```python
hazard_type=hazard.type.value,
location=hazard.location,
```

That is it. No new import; `hazard.type.value` is already the exact token written to `notification_log` by the activity-logger block one scope up (`safety.py:2537`), so the two sites now agree on their key.

**Blast radius in NM (R3-corrected).** Today every Safety alert reaches NM with `hazard_type=None`, so `is_life_safety_hazard()` returns False everywhere in NM. D1 flips the following NM policies at once for Safety life-safety tokens — the full set emitted at life-safety classification: `smoke`, `carbon_monoxide`, `flooding` (CRITICAL), `water_leak`, `freeze_risk` (HIGH), plus any tokens the operator has added via the `_nm_cycle_a.py:200-220` extras knob:

| # | Site | Behaviour today (hazard_type=None) | Behaviour post-D1 | Verdict |
|---|---|---|---|---|
| B1 | `_repeat_interval_for_active_alert` (`notification_manager.py:2578-2579`) + `_repeat_phase` (`:2634`) | 300 s decay ladder (`phase1=300 s` → `phase2` after `PHASE1_WINDOW_S` → `daily` after `DAILY_AFTER_S`). | Fixed **30 s** (`NM_REPEAT_INTERVAL_LIFE_SAFETY`), **never decays**. CRITICAL only (HIGH never enters ALERTING). | **INTENDED.** Life-safety contract (`const.py:3387`). D5 bounds the exposure (unacked repeats stop once the hazard key leaves `_active_hazards`). |
| B2 | Boot-settle collapse exemption (`notification_manager.py:1508-1509`) | Smoke/CO/flooding/leak/freeze alerts raised during the boot-settle window could be collapsed into the dedup bucket (silent). | Boot-settle collapse is bypassed for life-safety hazards — the alert raises immediately. | **INTENDED.** A life-safety hazard during boot must not be silenced. |
| B3 | DND safety floor at `async_notify` (`notification_manager.py:4184`) | DND veto applies, suppressing CRITICAL smoke/CO/flooding + HIGH water_leak/freeze_risk during quiet hours. | DND bypass applied — life-safety alerts page through DND. | **INTENDED.** DND safety floor is the stated design (R3: water_leak/freeze_risk inclusion deliberate). |
| B4 | Router per-recipient mute bypass (`notification_manager.py:4235`) | Per-recipient mute suppresses even CRITICAL smoke/CO (and HIGH water_leak/freeze_risk). | Per-recipient mute bypassed for life-safety. | **INTENDED (R3).** |
| B5 | Token-bucket bypass (`notification_manager.py:3889-3892, 3925, 4028`) | Rate limiter can drop life-safety alerts in a burst. | Token bucket bypassed for life-safety; always admitted. | **INTENDED (R3).** |
| B6 | Security-image override guard (`notification_manager.py:1480`) | A smoke/leak alert during a security image path could be deprioritised. | Life-safety path takes precedence. | **INTENDED.** |
| B7 | Boot-settle dedup bucket key (`notification_manager.py:658`) | Key `(coord, hazard_type)` was `("safety", "")` — a single shared bucket for all Safety hazards during boot. | Per-hazard buckets: `("safety","smoke")`, `("safety","carbon_monoxide")`, `("safety","flooding")`, `("safety","water_leak")`, `("safety","freeze_risk")`. | **INTENDED.** Dedup becomes correct per-hazard. |
| B8 | COOLDOWN_CONFIG lookup (post-ACK path, `notification_manager.py:196-205`) | Cooldown falls back to `DEFAULT_NM_COOLDOWN_DEFAULT` (keyed on `""`). CRITICAL-only path. | Smoke/CO → 120 s; flooding → 5 min. HIGH water_leak/freeze_risk never ACK through this gate (don't enter ALERTING). | **INTENDED.** Operator-tunable per-hazard cadence. |
| B9 **(new, R3)** | `_repeat_alert` life-safety mute/DND bypass (`notification_manager.py:2700` → `_recipient_bypasses_dnd` / `_route_for_recipient` at `:2711-2720`) | Repeat ticks (CRITICAL only, so smoke/CO/flooding) honour per-recipient DND + mute. | Repeats bypass DND and mute for life-safety CRITICALs. | **INTENDED.** Mirrors B3/B4 on the repeat path. |

**R3 restatement:** `water_leak` and `freeze_risk` are deliberately in `NM_LIFE_SAFETY_HAZARDS` (`const.py:3391-3399`); after D1 their HIGH-severity alerts begin to bypass DND, per-recipient mute, the token bucket, and leave the shared boot-settle bucket (B2-B5, B7). They do NOT enter ALERTING (B1/B8/B9 apply only to CRITICAL), so there is no new re-fire or 30 s repeat behaviour for them. The extras-knob union (`_nm_cycle_a.py:200-220`) extends the same classification to operator-added tokens. **This is the intended life-safety contract**; the previous "non-regression" paragraph was wrong and is removed.

**Build test anchor for the repeat-phase flip:** `test_safety_smoke_repeat_phase_is_life_safety` — construct a smoke CRITICAL through `_respond_to_hazard`, drive it to `REPEATING`, assert `nm._repeat_phase() == "life_safety"` and `nm._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_LIFE_SAFETY`. **RED on develop today** (hazard_type is None → returns `"phase1"` / 300 s). (This is T6.)

### D2 — Make `is_hazard_active` hold-aware (post-ACK gate ONLY)

Unchanged from Rev 2 code shape. **File / line:** `custom_components/universal_room_automation/domain_coordinators/safety.py:3398-3410`.

Reference implementation:

```python
def is_hazard_active(self, hazard_type: str, location: str) -> bool:
    """SAFETY-NM-REFIRE-UNWIRED-1: hold-aware — a key whose clear hold
    is pending (all contributors recovered, 300 s HAZARD_MIN_HOLD_S not
    yet elapsed) is reported INACTIVE so NM does not re-page a
    detector that has already recovered. A relapse cancels the hold
    (`_record_sensor_relapse`), which re-exposes the key here.

    Scope: this predicate is consumed ONLY by NM's post-ACK re-fire
    gate (`notification_manager.py:3034-3039`). The unacked REPEATING
    loop uses `is_hazard_key_present` instead (D5) — that predicate
    is NOT hold-aware so an unacked life-safety hazard is never
    silenced while its key is still retained in `_active_hazards`.
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

### D3 — Tests (quality/tests/safety/ and quality/tests/notification_manager/)

**14 tests total.** Each is explicitly classified as (R) regression guard (passes on develop today) or (F) fix-proving (fails on develop today, passes on build). The RED-on-develop subset is the discriminator — reviewers must verify each by running against develop before applying the patch.

| # | Name | File | Class | Mutation anchor |
|---|---|---|---|---|
| T1 | `test_safety_notification_action_carries_hazard_type_location` | `quality/tests/safety/` | **F** | Remove either `hazard_type=` or `location=` kwarg from D1 → assertion flips. |
| T2 | `test_safety_is_hazard_active_true_when_active` | `quality/tests/safety/` | **R** | Covers D2 non-regression on the already-shipped path. |
| T3 | `test_safety_is_hazard_active_false_when_cleared` | `quality/tests/safety/` | **R** | Covers D2 non-regression on the cleared path. |
| T4 | `test_safety_is_hazard_active_false_during_clear_hold` | `quality/tests/safety/` | **F** | Revert D2 → test fails (pending-clear key returns True on the hold-aware path). |
| T5 | `test_safety_is_hazard_active_true_on_relapse_during_hold` | `quality/tests/safety/` | **R** | Drives relapse through `_respond_to_hazard` (smoke binary-sensor flips back on) exercising `had_pending_clear` + `_LIFE_SAFETY_REARM_TYPES` at `safety.py:2487-2492`. |
| T6 | `test_safety_smoke_repeat_phase_is_life_safety` | `quality/tests/notification_manager/` | **F** | Remove either D1 kwarg → `_repeat_phase()` returns `"phase1"` and the assertion fails. |
| T7 | `test_nm_re_evaluates_safety_hazard_round_trip` | `quality/tests/notification_manager/` | **F** | Full post-ACK round-trip. Steps: (1) raise smoke via `_respond_to_hazard`; (2) assert ALERTING; (3) call `nm.async_acknowledge(...)` (ACK); (4) advance 120 s cooldown; (5) assert exactly ONE `async_notify(severity=CRITICAL)` call originating from `_re_evaluate_hazard` (count by patching the sole call site at `notification_manager.py:3046-3054`); (6) assert the call used `hazard_type="smoke"` and `location="<room>"` (not `("", "")`). Separately counts REPEATING-state ticks — not included in the "exactly one" count. |
| T7-neg | `test_nm_re_evaluate_no_refire_during_pending_clear` | `quality/tests/notification_manager/` | **F** | Negative twin of T7. Steps (1)-(3) as T7; smoke sensor recovers at t=60 s (hold armed, `_hazard_clear_pending` has the key); advance to t=130 s (cooldown expired, hold still running); assert ZERO re-fire `async_notify` calls from `_re_evaluate_hazard` and `_alert_state == IDLE`. Fails on develop with D1 but without D2 (would re-fire). |
| T8 | `test_nm_repeat_alert_stops_when_hazard_key_leaves_active_hazards` | `quality/tests/notification_manager/` | **F** | **D5 anchor (R1 fix).** Steps: (1) raise smoke CRITICAL, do NOT ack → enter REPEATING; (2) advance 30 s → assert one re-page row; (3) smoke sensor recovers at `t=recovery_ts` (hold armed, key STILL in `_active_hazards`, `_hazard_clear_pending` set); (4) advance 30 s past recovery → repeat tick → `is_hazard_key_present=True` → **still re-pages** (critical R1 assertion — unacked NOT silenced during hold); (5) advance to `recovery_ts + 300 s + ε` (past hold expiry) → trigger `_sweep_hazard_clears` → key popped from `_active_hazards`; (6) next `_repeat_alert` tick (within 30 s of pop) observes `is_hazard_key_present=False` → transitions to IDLE; (7) **R4 asserts (new):** `self._light_pattern_task is None` (or `.done() is True`), `_restore_alert_lights()` was awaited (patch and count), `_repeat_unsub is None`, DB row `acknowledged == 1`, audit row written with `route_reason="auto_cleared:safety_hazard_absent"`; (8) no further `notification_log` row. **RED on develop even after D1 alone.** Mutation anchors: revert D5 only → fails at step 6; drop R4 teardown → fails at step 7; use hold-aware predicate → fails at step 4 (R1 regression). |
| T8-fail-open | `test_nm_repeat_alert_fails_open_on_predicate_error` | `quality/tests/notification_manager/` | **R / post-build mutation anchor** | Classification corrected per R5. On develop `_repeat_alert` does not call the predicate, so the test passes trivially; after D5 lands, monkeypatch `safety.is_hazard_key_present` to raise, drive one tick, assert re-page emitted (clause 5(iii)). Mutation anchor: remove D5's `try/except` → test raises. |
| T9 | `test_safety_flooding_location_is_deterministic` | `quality/tests/safety/` | **F** | **D6 anchor (F7 fix, R7 upgrade).** Spawn two subprocess runs with `PYTHONHASHSEED=0` and `PYTHONHASHSEED=1` that each: construct `_active_leak_sensors` with locations `["Kitchen", "Garage"]` (insertion order fixed), run the location-composition path, and print the result. The parent test asserts both subprocess outputs equal `"Garage, Kitchen"` AND `== ", ".join(sorted(set(["Kitchen", "Garage"])))`. Mutation anchor: revert D6 → at least one of the two seeded runs produces `"Kitchen, Garage"` → test fails. (Rationale: in-process `set()` iteration is often stable within one PYTHONHASHSEED, so RED on develop requires crossing the hash-seed boundary.) |
| **T10** (new, R1) | `test_nm_repeat_alert_keeps_paging_on_relapse_in_dedup_window` | `quality/tests/notification_manager/` | **F** | R1 repro walk. Steps: (1) smoke ON t=0 → page (AlertDeduplicator stamps the hazard at `safety.py:961`); (2) assert `_alert_state == REPEATING`; (3) smoke OFF t=5 s (hold armed, key in `_active_hazards`, `_hazard_clear_pending` set); (4) advance to t=30 s → `_repeat_alert` tick → `is_hazard_key_present=True` → re-page row written at t=30 s; (5) smoke ON again t=40 s → `_respond_to_hazard` runs; the AlertDeduplicator window has not elapsed (40 < 60), so NO new NotificationAction is emitted by Safety, BUT the hold is cancelled (`_record_sensor_relapse`) and the key stays firmly in `_active_hazards`; (6) advance to t=60 s → `_repeat_alert` tick → `is_hazard_key_present=True` → re-page; (7) advance to t=90 s → re-page; (8) assert `notification_log` has at least four re-page rows between t=30 s and t=120 s. Mutation anchor: change D5 to use `is_hazard_active` (hold-aware) → the t=30 s tick returns False (hold pending, no raising sensors between t=5 and t=40), D5 transitions to IDLE, step 4 asserts fail; subsequent relapse paging also fails because NM is IDLE and the dedup window suppresses re-entry (the exact R1 silence). |
| **T11a** (new, R2) | `test_nm_repeat_alert_fails_open_on_empty_hazard_type` | `quality/tests/notification_manager/` | **F** | R2(i) anchor. Simulate `_recover_state_from_db` restoring REPEATING with `hazard_type=None` (pre-D1 row). Drive one `_repeat_alert` tick; assert a re-page row is written (clause 5(i) fail-open). Mutation anchor: remove the empty-key guard in D5 → `is_hazard_key_present("", "")` returns False → test fails (D5 silences the pre-D1 row). |
| **T11b** (new, R2) | `test_nm_repeat_alert_fails_open_before_safety_evaluated` | `quality/tests/notification_manager/` | **F** | R2(iv) anchor. Construct a fresh Safety coordinator with `_initial_evaluation_complete=False`; raise a smoke CRITICAL via mocked `async_notify` entry (bypass `_respond_to_hazard` since Safety is pre-evaluation); drive one `_repeat_alert` tick; assert re-page emitted (clause 5(iv) fail-open). Then flip `_initial_evaluation_complete=True`, drop smoke from `_active_hazards`, drive one more tick, assert IDLE. Mutation anchor: remove the boot-grace guard → first-tick re-page suppressed → test fails. |

**RED-on-develop subset (reviewer verification required):** T1, T4, T6, T7, T7-neg, T8, T9, T10, T11a, T11b. (10 fix-proving.)
**R / regression guards:** T2, T3, T5, T8-fail-open. (4.)
**Total:** 14.

### D4 — Doc updates (same commit as build, per CLAUDE.md §10 rule)

- `docs/Coordinator/SAFETY_COORDINATOR.md` §5: add a paragraph covering (a) `is_hazard_active` hold-aware post-ACK gate; (b) NEW `is_hazard_key_present` non-hold-aware predicate for the unacked repeat loop; (c) NEW `_initial_evaluation_complete` readiness flag; (d) D5 terminal cleanup reuses the ack path (`database.acknowledge_notification` + `_restore_alert_lights` + light-task cancel) with audit `route_reason="auto_cleared:safety_hazard_absent"`; (e) the 300 s clear hold interacts by design with the 120 s smoke/CO cooldown (post-ACK path, hold-aware) and the 30 s life-safety repeat cadence (unacked path, key-present only — repeats continue through the hold, stop ≤30 s after sweep pops the key).
- `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` §10: mark the SAFETY-NM-REFIRE-UNWIRED fold-out as "shipped v<next>" with back-link.

### D5 — Stop the unacked repeat loop when the hazard key has LEFT Safety's `_active_hazards` (R1 redesign)

**Target 1 (new predicate):** `custom_components/universal_room_automation/domain_coordinators/safety.py`, immediately below `is_hazard_active` at `:3398-3410`.

```python
def is_hazard_key_present(self, hazard_type: str, location: str) -> bool:
    """SAFETY-NM-REFIRE-UNWIRED-1 D5: NON-hold-aware key-membership
    predicate for NM's unacked REPEATING loop (notification_manager.py:
    _repeat_alert). Returns True iff the base key is in
    `_active_hazards`, IGNORING any pending clear hold.

    Why NOT hold-aware (R1): the unacked repeat loop must keep paging
    while the key is retained — silencing on a pending hold would
    suppress a chattering detector mid-recovery (ON→OFF→ON inside the
    60 s AlertDeduplicator window would land after NM dropped to IDLE
    and would not re-page). The loop transitions to IDLE only after
    `_sweep_hazard_clears` pops the key at `HAZARD_MIN_HOLD_S` expiry.

    Scope: this predicate is Safety-only. Security's analogue is
    deferred to SECURITY-REFIRE-INTRUSION-KEY-1.
    """
    exact = f"{hazard_type}:{location}"
    for active_key in self._active_hazards:
        base = active_key[:-4] if active_key.endswith(":roc") else active_key
        if base == exact:
            return True
    return False
```

**Target 2 (readiness flag):** `custom_components/universal_room_automation/domain_coordinators/safety.py`.

- In `__init__` (`safety.py:1013-...`): add `self._initial_evaluation_complete: bool = False`.
- In `_async_periodic_check` (the 1-min periodic method scheduled at `safety.py:1273-1276`): at the END of the method body, set `self._initial_evaluation_complete = True`. One-shot latch (checking `if not self._initial_evaluation_complete:` first is optional; `True = True` is idempotent).

**Target 3 (NM repeat loop):** `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:2645-2710` (inside `_repeat_alert`, immediately after the state / messaging-suppressed guards at `:2647-2650`, BEFORE the per-person fan-out at `:2696`).

```python
# SAFETY-NM-REFIRE-UNWIRED-1 D5: stop re-paging an unacked life-safety
# CRITICAL once the owning Safety coordinator has fully let go of the
# hazard key (`HAZARD_MIN_HOLD_S` elapsed, `_sweep_hazard_clears` has
# popped it from `_active_hazards`). Non-hold-aware by design (R1).
#
# Scope: ONLY coordinator_id == "safety". Byte-identical behaviour for
# every other coordinator (security sibling tracked under
# SECURITY-REFIRE-INTRUSION-KEY-1).
#
# Fail-open on EVERY error path (R2) — keep paging a live life-safety
# hazard rather than silence it on a bug.
data = self._active_alert_data
coord_id = data.get("coordinator_id", "")
if coord_id == "safety":
    hazard_type = (data.get("hazard_type") or "")
    location = (data.get("location") or "")
    still_present = True  # default: fail-open
    try:
        if not hazard_type or not location:
            # R2(i): empty key (e.g. pre-D1 recovered row) → fail-open.
            still_present = True
        else:
            cm = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            coord = cm.coordinators.get(coord_id) if cm else None
            if coord is None:
                # R2(ii): coord-manager missing / safety not loaded → fail-open.
                still_present = True
            elif not getattr(coord, "_initial_evaluation_complete", False):
                # R2(iv): boot grace — Safety has not evaluated its sensors
                # yet; `_active_hazards` is empty for the wrong reason.
                still_present = True
            else:
                still_present = coord.is_hazard_key_present(hazard_type, location)
    except Exception:
        _LOGGER.warning(
            "D5 is_hazard_key_present raised — failing open (keep paging) "
            "hazard=%s loc=%s", hazard_type, location, exc_info=True,
        )
        still_present = True

    if not still_present:
        _LOGGER.info(
            "Safety hazard %s at %s cleared (key popped from _active_hazards)"
            " — stopping repeat loop and resolving row",
            hazard_type, location,
        )
        # R4: perform the SAME teardown as async_acknowledge
        # (notification_manager.py:2886-2900), reusing
        # database.acknowledge_notification() because no non-ack
        # resolution DAO exists today.
        _snap = dict(self._active_alert_data) if self._active_alert_data else None
        if self._repeat_unsub:
            self._repeat_unsub()
            self._repeat_unsub = None
        if self._light_pattern_task and not self._light_pattern_task.done():
            self._light_pattern_task.cancel()
            self._light_pattern_task = None
        await self._restore_alert_lights()
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            try:
                await database.acknowledge_notification()
            except Exception:
                _LOGGER.debug("D5 DB resolve failed (swallowed)", exc_info=True)
        if _snap:
            try:
                await self._emit_audit_row(
                    coordinator_id="safety",
                    severity=Severity.CRITICAL,
                    title=f"[AUTO-CLEAR] {_snap.get('title') or ''}",
                    hazard_type=_snap.get("hazard_type"),
                    location=_snap.get("location"),
                    recipient_id=None,
                    channel="auto",
                    route_reason="auto_cleared:safety_hazard_absent",
                    dnd_bypass_applied=False,
                    bucket_outcome="auto_clear",
                    matrix_branch="auto_clear",
                    delivered=1,
                    dry_run=0,
                    acknowledged=1,
                )
            except Exception:
                _LOGGER.debug("D5 audit row emit failed (swallowed)", exc_info=True)
        self._alert_state = AlertState.IDLE
        self._active_alert_data = None
        async_dispatcher_send(self.hass, SIGNAL_NM_ALERT_STATE_CHANGED)
        async_dispatcher_send(self.hass, SIGNAL_NM_ENTITIES_UPDATE)
        return
```

**Discharge (per "Suppression needs a discharge"):** this is a terminal transition to IDLE with full teardown — not a suppression. (i) Repeat tick listener implicitly cancelled by the state guard at `:2649` on the next scheduling pass, and explicitly by `_repeat_unsub()`. (ii) `_light_pattern_task` cancelled and lights restored (R4). (iii) DB row marked `acknowledged=1` so `get_active_critical` cannot resurrect it on restart. (iv) Audit row written with distinguishing `route_reason`. No lingering timer, no residual state.

**Non-Safety coordinators:** `coord_id != "safety"` branch is skipped entirely → byte-identical behaviour for every non-Safety repeat path. (Security will adopt the same pattern once `SECURITY-REFIRE-INTRUSION-KEY-1` lands.)

**Fail-open proof obligations:** T8-fail-open, T11a (empty key), T11b (boot grace).

### D6 — Deterministic flooding location (F7)

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

**Rationale:** `set()` iteration order is non-deterministic across process restarts (hash randomisation) so a flooding hazard raised, cleared partway, then re-keyed may not match itself in `_active_hazards` → `is_hazard_key_present` / `is_hazard_active` return False on a still-active multi-sensor flood. One-line, in-cycle per Fix LOWs In-Cycle. T9 is the anchor (dual `PYTHONHASHSEED` subprocess run per R7).

## 6. Non-goals

- No change to NM cooldown defaults (`DEFAULT_NM_COOLDOWN_SMOKE=2` etc.).
- No change to the life-safety hazard set (`NM_LIFE_SAFETY_HAZARDS`).
- No new `NotificationAction` emission sites, no new DAO, no schema change. (`acknowledge_notification` reused; no `resolve_notification` sibling added — R4 alternative-considered.)
- No change to `BaseCoordinator` — `is_hazard_key_present` is added to `SafetyCoordinator` only.
- No behaviour change for non-life-safety Safety hazards at the ALERTING / cooldown / repeat machinery (they never enter ALERTING). D1 only affects their boot-settle, DND, mute, and token-bucket classification — INTENDED (R3).
- Not re-opening SAFETY-HAZARD-NEVER-CLEARS-1 — treat its machinery (`_hazard_clear_pending`, `_sweep_hazard_clears`, `HAZARD_MIN_HOLD_S`, `_record_sensor_recovery/_relapse`) as a stable primitive to be read.
- **Not fixing** `security.py:825-828` (`"intrusion"` vs `"intruder"` token mismatch — F4). Separately carded as **`SECURITY-REFIRE-INTRUSION-KEY-1`**.
- **Not** applying D5 to coordinators other than Safety.

## 7. Knobs on the ladder

Rule: "Numbers get knobs". New numbers introduced here: **none**. Reused numbers and their rung:

| Number | Rung | Home | Why |
|---|---|---|---|
| `HAZARD_MIN_HOLD_S = 300` | 1 (module const in `safety.py`) | shipped v5.103.61 | Safety-semantics bound. |
| `DEFAULT_NM_COOLDOWN_SMOKE/_CO = 2 min` | 2 (options flow) | `const.py` COOLDOWN_CONFIG | Operator-tunable paging cadence. |
| `DEFAULT_NM_COOLDOWN_FLOODING = 5 min` | 2 (options flow) | `const.py` COOLDOWN_CONFIG | Operator-tunable. |
| `NM_REPEAT_INTERVAL_LIFE_SAFETY = 30 s` | 1 (module const) | `const.py:3387` | Safety contract. |

New boolean / helper added here: `Safety._initial_evaluation_complete` (not a tunable — a readiness latch, Rung 1 by definition).

## 8. Acceptance criteria (R6 timing corrected)

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
- **Verify:** T2, T3, T4, T5.
- **Live (DB):**
  ```sql
  SELECT id, timestamp, hazard_type, location, acknowledged, ack_time,
         cooldown_expires
    FROM notification_log
   WHERE coordinator_id='safety' AND severity='critical'
     AND timestamp > datetime('now','-1 day')
   ORDER BY id DESC;
  ```
  Expect: exactly one row per real still-active ACK'd life-safety event (the re-fire row carries the same `hazard_type` + `location` and a later `timestamp`), and zero re-fire rows whose `hazard_type` was in `_hazard_clear_pending` at the time of cooldown expiry.

### D5 — unacked repeat loop stops on key-popped (R6 timing)
- **Verify (unit):** T8, T10, T11a, T11b, T8-fail-open.
- **Live (DB):** after a smoke / CO test fire where no human acks:
  ```sql
  SELECT id, timestamp, hazard_type, location, acknowledged, route_reason,
         bucket_outcome
    FROM notification_log
   WHERE coordinator_id='safety' AND severity='critical'
     AND hazard_type IN ('smoke','carbon_monoxide')
     AND timestamp > datetime('now','-1 hour')
   ORDER BY id ASC;
  ```
  Expect: a cluster of repeats at ~30 s cadence spanning (first_page_ts, recovery_ts + 300 s), followed by a **terminal row within ≤30 s after `recovery_ts + 300 s` (i.e. ≈ 5.5 min after sensor recovery)**. The terminal state is marked by `database.acknowledge_notification()`: the last row in the cluster has `acknowledged=1` and (via the auto-clear audit emitted by D5) a sibling audit row with `route_reason='auto_cleared:safety_hazard_absent'` and `bucket_outcome='auto_clear'`. Regression threshold: if `notification_log` rows for the same `(coordinator_id='safety', hazard_type, location)` continue past `recovery_ts + 360 s` → D5 regressed. Conversely, if the cluster STOPS before `recovery_ts + 300 s` (e.g. 30 s after recovery) → R1 regression (D5 reverted to hold-aware).

### D6 — deterministic flooding location (F7, R7)
- **Verify (unit):** T9 (dual `PYTHONHASHSEED` subprocess run).
- **Live:** on any multi-sensor flood, the `location` column alphabetises the room names (operator-visible via dashboard + DB).

### D3 — tests
- **Test:** all 14 functions PASS on build. Per-test mutation anchors in §5 D3.
- **RED-on-develop subset (reviewer must verify before applying patch):** T1, T4, T6, T7, T7-neg, T8, T9, T10, T11a, T11b.
- **Regression guards (GREEN on develop):** T2, T3, T5, T8-fail-open.

## 9. Review framings (Tier 2-DB, three framing-disjoint reviews)

- **A — data integrity + payload shape.** Every `NotificationAction` emission site in `safety.py` still well-formed? `notification_log` row shape unchanged (D1 adds no columns)? Any `Hazard` construction site missing `location` (would crash)? D6's `sorted(...)` round-trips through the DB cleanly? D5's auto-clear audit row shape matches the ack-path audit row (same columns, same types)?
- **B — migration correctness + signal chain integrity (both paths + predicate split).** Full trace from `_respond_to_hazard` → `manager.py:1070` → `NM.async_notify` → (post-ACK path) `_cooldown_expired` → `_re_evaluate_hazard` → **`is_hazard_active`** → re-fire, AND (unacked path) `_enter_alerting` → `_schedule_repeat` → `_repeat_alert` → **`is_hazard_key_present`** (NOT `is_hazard_active`) → either re-page or IDLE+teardown. Does the smoke/CO 2 min cooldown + 30 s repeat interact correctly with the 300 s clear hold at every reachable state (active, recovering mid-cooldown, relapsing mid-cooldown, cleared before cooldown fires, cleared during REPEATING with hold pending, cleared during REPEATING with hold elapsed and key popped, relapsing during REPEATING, pre-D1 restored REPEATING row post-restart, boot-grace window)? Enumerate every `is_hazard_active` / `is_hazard_key_present` reader (`grep: 'coordinator.is_hazard_active\|coordinator.is_hazard_key_present\|self.is_hazard_active\|self.is_hazard_key_present'`) and confirm the correct predicate at each site. Confirm D5 preserves byte-identical behaviour for every non-Safety coordinator. Confirm `_initial_evaluation_complete` cannot be stuck False after a successful setup (verify the 1-min periodic fires unconditionally — `safety.py:1273-1276`).
- **C — new surfaces + test fixture authority.** Mutation-anchor every test in D3: delete the `hazard_type=` kwarg → T1 and T6 fail; revert D2 → T4 fails; revert D5's key-present predicate (replace with hold-aware) → T8 and T10 fail; drop D5's empty-key guard → T11a fails; drop D5's boot-grace guard → T11b fails; drop D5's R4 teardown block → T8 R4 asserts fail; revert D5's try/except → T8-fail-open fails; revert D6 sorted → T9 fails under at least one `PYTHONHASHSEED`. Verify T10 drives the real `_respond_to_hazard` path for the t=40 s relapse (NOT a direct `_active_hazards[key] = ...` write), so the AlertDeduplicator window is really exercised. Verify T8 asserts the DB row's `acknowledged` column flips to 1 and the audit row's `route_reason` is exactly `"auto_cleared:safety_hazard_absent"`.

**Life-safety discriminator (post-deploy):** the `notification_log` DB row is the authoritative signal, not the log string. A sentinels-only log = payload-shape failure.

## 10. Open questions

1. **Pending-clear discriminator ambiguity (resolved).** D2 reports both "already cleared" and "pending-clear hold running" as `is_hazard_active == False`. Operator-facing consequence on the ACK path: during the 300 s pending-clear window the NM post-ACK re-fire gate sees "cleared" while the dashboard safety-alert entity still reads ON (deliberate, orchestrator ruling 2026-10-15 Q1). **Rev 3 clarification:** on the UNACKED path the behaviour is deliberately different — the key-present predicate (D5) keeps paging through the hold. Both are intended.
2. ~~Non-life-safety re-fire.~~ **Withdrawn** (F1).
3. **`fire` and `intruder` not emitted by Safety.** Reference only; carded under `SECURITY-REFIRE-INTRUSION-KEY-1`.

## 11. Orchestrator rulings on open questions (2026-10-15)

- **Q1:** YES. While a hazard's clear hold is pending on the ACK path, the dashboard may read ON for up to 300 s while the NM post-ACK re-fire gate reads cleared. On the UNACKED path, the repeat loop continues to page through the hold (deliberate per R1).
- **Q2 (Rev 2 revision):** no change to NM's re-fire policy for non-CRITICAL hazards (they never reach ALERTING).
- **Q3:** carded as `SECURITY-REFIRE-INTRUSION-KEY-1`.
- **R1 (Rev 3):** D5 does NOT use the hold-aware predicate. A dedicated non-hold-aware `is_hazard_key_present` predicate is added. D2's `is_hazard_active` stays scoped to the post-ACK gate.
- **R2 (Rev 3):** D5 fails OPEN on empty key, missing coordinator-manager/coordinator, predicate exception, and boot grace (`_initial_evaluation_complete=False`). Readiness flag is NEW (justified).
- **R3 (Rev 3):** `water_leak` / `freeze_risk` in `NM_LIFE_SAFETY_HAZARDS` is deliberate; D1's DND/mute/token-bucket bypass for their HIGH alerts is INTENDED. The repeat-path bypass site at `:2700` added as B9.
- **R4 (Rev 3):** D5 terminal cleanup REUSES ack-path teardown. `database.acknowledge_notification()` reused as the resolution write (no `resolve_notification` DAO added). Audit row carries `route_reason="auto_cleared:safety_hazard_absent"`.
- **R5/R6/R7 (Rev 3):** test count/classification fixed; R1 (T10) and R2 (T11a/T11b) tests added; R4 teardown asserts added to T8; T9 forces non-trivial order via dual `PYTHONHASHSEED` subprocess run; D5 live-check timing corrected to recovery_ts + ~330 s terminal row, regression threshold recovery_ts + 360 s.

---

### Rev 3 changelog
- §0 Review-resolution table replaced with Rev 2 re-review resolutions (R1-R7).
- §1 invariant rewritten: predicates split per path (`is_hazard_active` post-ACK only; new `is_hazard_key_present` for unacked). Clause 2 (pending-clear) now distinguishes the two paths. Clause 5 fail-open expanded (empty key, missing CM, predicate exception, boot grace).
- §2 institutional context expanded: NEW `is_hazard_key_present` and NEW `_initial_evaluation_complete` with justification; ack-path teardown added as R4 reuse target; `database.acknowledge_notification` reuse rationale.
- §4 consumer map updated: D5 now consumes `is_hazard_key_present`, not `is_hazard_active`.
- §5 D1 blast-radius table restated (R3): water_leak/freeze_risk inclusion deliberate; row B9 added for `:2700` repeat-path mute/DND bypass.
- §5 D2 docstring clarifies it is the post-ACK gate only (unacked path uses D5's new predicate).
- §5 D3 rewritten: 14 tests, correct classification; T8-fail-open re-classed R / post-build mutation anchor; T10 added (R1 relapse-in-dedup-window); T11a / T11b added (R2 empty-key / boot-grace); T8 extended with R4 teardown asserts; T9 upgraded to dual `PYTHONHASHSEED` subprocess run.
- §5 D5 redesigned: new predicate target, new readiness flag target, R4 teardown block (ack-path reuse + audit row), all four fail-open guards; discharge covers each.
- §6 non-goals updated (`is_hazard_key_present` scoped to SafetyCoordinator; no new DAO).
- §7 knob ladder notes the new readiness latch.
- §8 live timing rewritten (recovery_ts + ~330 s terminal row; recovery_ts + 360 s regression threshold); SQL extended with `route_reason` + `bucket_outcome` columns.
- §9 review framings call out the predicate split and `_initial_evaluation_complete` liveness check.
- §11 rulings extended with R1-R7.
