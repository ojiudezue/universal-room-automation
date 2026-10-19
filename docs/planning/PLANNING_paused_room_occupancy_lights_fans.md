# PLANNING: paused rooms stop occupancy-driven lights and fans (HVAC tier + fan recheck)

Card: ROOM-OVERRIDE-SWITCH-FORGOTTEN-1 (`docs/planning/kanban.data.yaml:31063`). Audit: `docs/planning/AUDIT_paused_rooms_light_fan_paths_2026_10_18.md` (read in full).
Base: `develop` at `f9fb1f5ba` (includes v5.103.73 fan-recheck still-risk veto scope). Date 2026-10-18.
Read first: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (read COMPLETELY for this plan; nothing in its §10 ledger is re-asserted here), `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §"Fan pause-recheck" (lines ~372-396).

## 0. Operator ruling (the spec)

- **2026-10-18, verbatim (supersedes the 10-17 "paused rooms should be inert" answer and options A/B):** "Paused rooms should stop with lights and fans automation based on occupancy. Blinds down, house state, venting are fine. I just didn't want it turning off lights when paused."
- **10-17 answer (superseded):** "Paused rooms should be inert". A paused room would issue no actions at all. Kept here only so a reviewer does not widen scope back to it.

**Scope (orchestrator reading, already told to the operator).** Three ungated writers are gated on the room Automation switch:
- **L1:** the HVAC zone vacancy sweep.
- **F1:** HVAC comfort fans.
- **F2:** the fan recheck.

These are NOT gated:
- F3 sleep-onset fan ON
- F4 pre-arrival fans
- covers
- AI and house-state chained rules
- humidity venting
- safety shutdowns
- `turn_off_all_managed`

## 1. Institutional context verified

**Config-first check.** No setting fixes this.
- **Zone sweep switch** (`switch.ura_hvac_coordinator_zone_sweep`, `zone.vacancy_sweep_enabled`): zone-wide. Turning it off also stops the sweep in unpaused rooms of the same zone. Not equivalent.
- **Fan Mode = Off on each paused room** (`select.<room>_fan_mode`, `const.fan_owner` at `const.py:1296`): this does stop F1/F2 (and F3/F4). It is still rejected:
  - it is a second knob that has to be kept in sync with the pause switch;
  - unpausing does not restore the room's Fan Mode;
  - it does nothing for L1 lights, which is the operator's actual complaint ("turning off lights when paused").
- **Conclusion:** code is warranted. The knob is the room Automation switch the operator already uses.

**Prior-art scan, REUSE or BUILD for each piece:**

| Piece | Verdict | Evidence |
|---|---|---|
| "Is this room paused?" | **REUSED** `RoomCoordinator._is_automation_enabled` at `coordinator.py:3181` (manual_mode ON → disabled; `automation` switch off → disabled; switch missing → enabled). Switch entity `AutomationSwitch` at `switch.py:5103`. | Its only consumers today are `coordinator.py:5235`, `automation.py:890` and `actuator_reconciler.py:544`. Grepping `_is_automation_enabled` across `domain_coordinators/` returns 0 hits, so no HVAC or presence code reads it (audit §2, re-run 2026-10-18). |
| Shared predicate wrapper `room_automation_paused(room_coord) -> bool` | **NEW** (one ~10-line function, in `const.py` next to `fan_owner` at `const.py:1296`, which is the existing home for the cross-tier duck-typed ownership rule that `hvac_fans` and `presence_fan_recheck` already import). Need: three call sites in two modules, each with a different coordinator lookup, and each would otherwise hand-roll a private-method call plus exception handling. | Searched `const.py`, `hvac_fans.py`, `presence_fan_recheck.py`, `fan_veto.py` and `hvac.py` for `paused`, `automation_enabled` and `room_automation`. Nothing equivalent exists. `fan_veto.py` is house-AWAY-specific, so it is the wrong home. |
| Room coordinator lookup in hvac.py | **REUSED** `HVACCoordinator._get_room_coordinator` `hvac.py:6942` (already called in the sweep loop `hvac.py:6730`) | — |
| Room coordinator lookup in recheck | **REUSED** `FanRecheckManager._room_coord_for` `presence_fan_recheck.py:1341`; `_evaluate_eligibility` already receives `room_coord` | — |
| Room coordinator lookup in FanController | **NEW, small accessor**: `FanController` resolves config only (`_live_room_merged` `hvac_fans.py:1209`). Add `_room_coord(room_name)` with the same shape as `_room_coord_for` (entry scan → `hass.data[DOMAIN][entry_id]`) | No coordinator lookup exists in `hvac_fans.py` (grep `_get_room_coordinator\|_room_coord` = 0) |
| F1 "stop managing, never actuate" semantics | **REUSED**: the release branch of `_is_room_hvac_managed` (`hvac_fans.py:1245-1287`; clears `is_on`/`trigger`/`speed_pct`/`last_on_time`/`vacancy_detected_time`, writes nothing) and its hand-back adoption (physically-on fan → manual-ON hold). Doctrine: STATE_OF_PLAY §4.2b "Leaving Follow thermostat RELEASES tracking and never turns the fan off". | — |
| F2 veto shape | **REUSED**: the `sink.veto(room_name, "<reason>")` ladder in `_evaluate_eligibility` (`presence_fan_recheck.py:514+`; `room_disabled` at :546 is the sibling) + arm-delay twin `_still_armed_eligible` (:1213). New veto reason string `room_paused`. | — |
| Vacancy-sweep per-room skip shape | **REUSED**: the existing per-room `continue` in `_execute_vacancy_sweep` (`hvac.py:6728-6731` coordinator-None skip; :6799-6804 fan-owner skip) | — |
| New knob | **None.** The room Automation switch is the knob; no behavioural number is introduced. | — |

Prior plans/docs consulted:
- the audit above;
- `PLANNING_fan_noise_running_rejection.md` Rev 2 (C1a `leave_off`), skimmed;
- STATE_OF_PLAY §4.2b (Fan Mode as the one rule for every fan writer) and §3.2 (retreat gate consumers);
- card body `verify_2026_10_18_overnight`, `operator_answer_2026_10_17`, `operator_answer_2026_10_18`, `disposition_2026_10_15_overnight` (the Away leave-on sweep already skips paused rooms, per the 2026-09-30 ruling at `automation.py:885-893`; this plan extends the same ruling to the HVAC tier).

Code read:
- `hvac.py` 3025-3047 (row-1 sweep call), 3105-3125 (D6 sweep call), 6713-6830 (`_execute_vacancy_sweep`), 6942 (`_get_room_coordinator`);
- `hvac_fans.py` 100-130, 625-650 (`update` loop), 1209-1287;
- `presence_fan_recheck.py` 380-395, 462-551, 1213-1245, 1341-1347;
- `coordinator.py` 3170-3200.

## 2. Falsifiable invariants

- **INV-P (gate):** while a room's `_is_automation_enabled()` is False, the room's configured lights and night lights get **no `turn_off` from `_execute_vacancy_sweep`**, and its fans get no `turn_on`/`turn_off` from (a) the sweep, (b) `FanController.update` for that room (temp on/off/speed and external-change adoption), or (c) a fan-recheck **arm/pause**. This holds in every reachable path: row-1 vacant_past_grace, D6 stale-occupancy, any house state, either Fan Mode.
- **INV-Z (no retreat drift):** for any zone, the preset S1 writes, the `climate_write` rows, `zone.vacancy_sweep_done`, and `_vacancy_sweeps_today` are byte-identical whether or not some of the zone's rooms are paused.
  - Pausing affects only the actuation of the paused room's own lights and fans.
  - Reason, from the code: the retreat decision is taken before and independent of the sweep. `_execute_vacancy_sweep` returns None and its result is not read. `vacancy_sweep_done` is set by the caller (`hvac.py:3044-3046`, `:3119-3123`).
  - Occupancy is unchanged: a paused room still computes `STATE_OCCUPIED` (`coordinator.py:5382` else-branch). `hvac_occupied` and `any_room_occupied` are produced exactly as today.
- **INV-N (no-op path):** with no room paused, every gated site behaves byte-identically to today. The predicate is one extra read and returns False.

**Falsifiers a reviewer should try:**
- A paused room in a zone where the D6 branch sweeps.
- A paused room whose coordinator is None. That case is already skipped today and stays unchanged.
- `manual_mode` ON with `automation` ON. It must count as paused, because that is how the predicate behaves.
- A room paused while a recheck is PAUSED (§4 D3).
- Unpause inside a vacancy where `vacancy_sweep_done` is already True (§5).

## 3. Producer / consumer

- **Producer: `_is_automation_enabled`** (`coordinator.py:3181`). It reads the room's `manual_mode` and `automation` switch states through `_get_room_switch_state` (`coordinator.py:3028-3074`, with a cached entity id and a registry re-resolve).
  - Dependencies are healthy. The 20 rooms paused live (audit §3a) read `off` continuously, restored across restarts.
  - Missing switch → enabled (fail-open, today's behaviour preserved). An exception inside the wrapper also → not paused (fail-open, matching the missing-switch default). Fail-open is acceptable because the failure mode is today's behaviour, not a new harm.
- **Consumers after the change:** all trust/actuation decisions.
  - Existing: `coordinator.py:5235`, `automation.py:890`, `actuator_reconciler.py:544`.
  - New: `hvac.py` `_execute_vacancy_sweep` per-room loop; `hvac_fans.py` `update` per-room loop; `presence_fan_recheck.py` `_evaluate_eligibility` and `_still_armed_eligible`.
- **Secondary consumer (side effect to size):** `is_recheck_eligible` (`presence_fan_recheck.py:462`) feeds the room coordinator's D2 mmwave-fan demotion defer.
  - A paused room becomes ineligible, so D2 is no longer deferred and fires as the backstop, as it already does for `room_disabled` and `fan_control_off`.
  - This changes only the paused room's occupancy computation, never its actuation (actuation is gated). It does feed HVAC `hvac_occupied`.
  - It is the same outcome as any other recheck-ineligible room, so it is accepted and not a new class.

## 4. Deliverables

### D1. Shared predicate `room_automation_paused`
In `const.py` next to `fan_owner`: `def room_automation_paused(room_coord) -> bool`.
- It returns True only when `room_coord` exposes a callable `_is_automation_enabled` that returns exactly `False`.
- `None`, a missing attribute or an exception → False.
- It never raises.

**Acceptance**
- **Test:** `test_paused_room_gates.py::test_predicate_truth_table` covers coordinator None; no method; automation off; manual_mode on; both on; raises → False.
- **Verify:** `grep -rn "_is_automation_enabled" custom_components/universal_room_automation/domain_coordinators/` shows 0 hits. The three new sites call only `room_automation_paused`; nothing hand-rolls a second path.

### D2. L1: zone vacancy sweep skips paused rooms
In `_execute_vacancy_sweep` (`hvac.py:6728` loop), right after the coordinator-None `continue`, add `if room_automation_paused(coordinator): continue`, with one DEBUG line naming the room.
- Lights, night lights and fans are all skipped for that room.
- No change at the two call sites, to `vacancy_sweep_done`, or to `_vacancy_sweeps_today`.

**Acceptance**
- **Test:** `test_sweep_skips_paused_room_lights_and_fans`. A zone has rooms A (paused) and B (enabled), both with lights on and HVAC-owned fans. A gets 0 `turn_off` calls and B gets them all.
  - Discriminates against a zone-level skip (that would give B 0 calls too) and against no gate (that would give A calls).
- **Test:** `test_sweep_paused_room_d6_branch`. Same assertion reached through the D6 stale-occupancy caller (`hvac.py:3119`).
- **Test:** `test_zone_retreat_unchanged_with_paused_room` (INV-Z). The same tick is run twice (A paused, then A enabled). The S1 preset write, `vacancy_sweep_done` and the sweep counter are equal; only the `turn_off` set differs.
- **Live:** for 72 h after deploy, the HA recorder shows 0 transitions in paused rooms where (a) `context_parent_id` is the URA ULID (`ura_context.py:55`), (b) the transition is on→off on a configured light or switch of a paused room, and (c) the same second has a zone `climate_write ... reason=vacant_past_grace`. Audit baseline: 3 such rows in 7 days.

### D3. F1 HVAC comfort fans + F2 fan recheck skip paused rooms
**F1.** In `FanController.update` per-room loop (`hvac_fans.py:635`), right after the `_is_room_hvac_managed` skip, add `if room_automation_paused(self._room_coord(room_name)): <release>; continue`.
- `<release>` is the existing release behaviour, done once on the transition into paused: clear `is_on`, `trigger`, `speed_pct`, `last_on_time` and `vacancy_detected_time`, with one INFO line. It writes nothing.
- The builder must factor the release out of `_is_room_hvac_managed` into a helper so there is one copy. The site sits before the external-change sync, so a paused room's manual fan use opens no cooldown or hold.
- The `_set_fan_state` chokepoint is NOT gated. F2 restore, F3, the safety stop and `turn_off_all_managed` all route through it and are out of scope.

**F2.** In `_evaluate_eligibility`, after the `room_disabled` veto (:546), add `if room_automation_paused(room_coord): return sink.veto(room_name, "room_paused")`. The same check goes into `_still_armed_eligible`, so an ARMED (not yet paused) room disarms on its next check.
- A recheck already PAUSED when the operator flips the switch is NOT cut short. It completes, and its restore is a discharge that must run: suppress-until clear, room-tier `note_recheck_restore`, and fan back to its snapshot.
- Gating the restore would strand the fan off. That is the one harmful option, so it is excluded.

**Acceptance**
- **Test:** `test_fan_controller_skips_paused_room`. A paused room with HVAC-owned fans, warm, and occupancy vacant past hold gets 0 `_set_fan_state` calls. An enabled twin gets its OFF.
- **Test:** `test_fan_controller_paused_release_no_write`. Pausing a room whose fan is tracked ON clears tracking and calls no service. On the next tick a physical external toggle books no cooldown.
- **Test:** `test_fan_recheck_vetoes_paused_room`. Eligibility returns False with veto counter `room_paused`. `is_recheck_eligible` returns False. `_still_armed_eligible` returns False.
- **Test:** `test_fan_recheck_paused_mid_flight_restores`. The room is paused while the recheck is PAUSED. The restore still writes the snapshot state.
  - Discriminates against gating the restore: under that wrong build the fan would stay off.
- **Test (scope fence):** `test_sleep_onset_and_prearrival_not_gated_by_pause`. F3 `_sleep_onset_activation` and F4 `_activate_zone_fans`/`_deactivate_zone_fans` still act in a paused room. This pins the non-goal so a later "tidy-up" can't widen the gate silently.
- **Live:** for 72 h, `ura_activity_log` has 0 `fan_off`/`fan_on` rows with `trigger` in {`temp_hvac`, `recheck_pause`} for a paused room. Audit baseline: Kitchen 6+6 and Master Bedroom 5 in 7 days.
  - The `fan_recheck` veto counters show `room_paused` > 0 for Kitchen if its mmwave-sole condition arises.
  - Discriminating companion: unpaused fan rooms (e.g. Jaya Bedroom by day) still show `temp_hvac` rows, which proves the gate is per-room and not a dead controller.

### D4. Doc write-back (same commit)
- **PRESENCE STATE_OF_PLAY:** fan-recheck item 3 gets the `room_paused` veto; §4/4.5 room-switch notes now say "the Automation switch now also gates the HVAC zone sweep, HVAC comfort fans, fan recheck".
- **HVAC STATE_OF_PLAY:** §4.2b, a new bullet saying a paused room is skipped by the sweep and FanController, and F3/F4 are not gated; header currency line.
- **Card:** the `verify_2026_10_18_overnight` correction (audit §5).

**Acceptance**
- **Verify:** both docs carry the lines in the build commit.

## 5. Unpause behaviour: no catch-up (decided, with reasons)

- **Sweep:** `vacancy_sweep_done` is zone-scoped and set once per vacancy. A room unpaused mid-vacancy keeps its lights on until the next zone vacancy, or until the room tier acts on its next occupancy edge or scheduled auto-off.
  - A catch-up would mean either a per-room "owed sweep" ledger or re-arming `vacancy_sweep_done` on an unpause edge. Both add a new cross-coordinator edge listener (switch → HVAC) on a rare-fire path.
  - The benefit is one late OFF of a light the operator just chose to hand back. Margin does not pay; PARKED. Revival trigger: the operator reports lights left on after unpausing.
- **F1:** on unpause, the next `update()` treats the room like a Fan Mode hand-back (existing path). A fan that is physically on is adopted as a manual-ON hold, not forced off; one that is off resumes normal temperature logic.
  - This is the documented doctrine for re-handing fans (§4.2b) and needs no new code.
- **F2:** eligibility re-opens on the next tick, with no state to restore.

## 6. Emission/decision-site enumeration (re-run 2026-10-18 on `f9fb1f5ba`)

| Site | Action | Gated by this plan? |
|---|---|---|
| `hvac.py:6713` `_execute_vacancy_sweep`, callers `:3044` (row-1), `:3119` (D6) | lights/night lights/fans OFF | **YES (D2)**, inside the function, so both callers are covered |
| `hvac_fans.py:569` `update` → `_evaluate_temp_fan` → `_set_fan_state` `:920` | temp fan on/off/speed + external-change adoption | **YES (D3)**, at the per-room loop |
| `presence_fan_recheck.py` `_evaluate_eligibility` / `_still_armed_eligible` → `_fan_pause` :1625 → `pause_for_recheck` `hvac_fans.py:2079` | fan OFF probe | **YES (D3)**, at arm |
| `restore_after_recheck` (`presence_fan_recheck.py:1647` → `hvac_fans.py:2138`) | restore | NO (discharge) |
| `hvac_fans.py:986` sleep-onset (F3) | fan ON | NO (house-state, operator scope) |
| `hvac_predict.py:1440` / `hvac.py:7375` pre-arrival (F4) | fan on/off | NO (anticipatory) |
| `hvac.py:2451` → `hvac_fans.py:532` `turn_off_all_managed`; `hvac.py:6585` `_stop_all_fans_safety` | fan OFF | NO (kill switch / safety) |
| Room tier `coordinator.py:5235`, `automation.py:890`, `actuator_reconciler.py:544` | lights/fans | already gated |
| Humidity `coordinator.py:5421`, covers `:5398`, AI/chained `:955/:996/:1281`, safety/security/NM | various | NO (operator: fine) |

The builder must re-run this grep before the build. Command: `grep -n "turn_off\|turn_on\|_set_fan_state" hvac.py hvac_fans.py hvac_predict.py presence_fan_recheck.py`. Any new fan or light writer reached from a per-room occupancy decision is a finding.

## 7. Non-goals
- No change to F3, F4, `turn_off_all_managed`, safety stops, humidity venting, covers, AI/house-state chained rules, or the Away leave-on sweep (already gated).
- No change to occupancy computation, `hvac_occupied`, zone retreat, S1, or the borrow primitive.
- No unpause catch-up (§5, parked).
- No forgotten-pause reminder. It stays a separate optional item on the card.
- No new knob, no new switch, no DB/schema change, no new activity-log action. The existing DEBUG/INFO lines and the `room_paused` veto counter are enough.
- Guest Bedroom 2 10-16 unattributed OFF: not investigated here (audit §5).

## 8. Tier

**Tier 2** (as briefed). There are three sites in three HVAC/presence modules and a small new predicate, with no state machine threaded and no cost/safety value. **Reviewer note:** the CLAUDE.md standing policy elevates cross-coordinator presence ↔ HVAC ripple to the Tier 2-DB review protocol (3 framing-disjoint reviews). I recommend elevating build review to 3 framings:
- A: per-site correctness and fail-open;
- B: INV-Z, no retreat drift, and the recheck mid-flight / D2-backstop side effect;
- C: per-site mutation, deleting each `room_automation_paused` check in turn must fail a named test.

The plan itself needs ONE adversarial plan review (Tier 2), dispatched by the orchestrator.

---

## Plan review 2026-10-18 (Tier-2 adversarial, ura-planner): FIX-PLAN

The reviewer read `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely, plus the audit and the presence fan-recheck section. No §10 ledger claim is re-asserted. All greps were re-run on `f9fb1f5ba`.

**Verified as the plan states**
- The room tier is fully gated. Every room-tier light/fan writer is reached only through `handle_occupancy_change`, `handle_temperature_based_fan_control` or `check_scheduled_auto_off` inside `coordinator.py:5235`, or through the Away sweep (`automation.py:890`) or the reconciler (`actuator_reconciler.py:544`).
  - This includes the room-tier sleep-onset twin `_maybe_sleep_onset_activate`, called at `automation.py:2810` from the gated temperature path.
- Files that make service calls outside that set: the HVAC trio, safety/security/NM/alert-light aggregation, perimeter, music, energy pool/EV switches, and the optimizer (shadow). None of them is a room-occupancy light/fan writer.
- **INV-Z, sweep part, holds.** `_execute_vacancy_sweep` returns None. `vacancy_sweep_done` and `_vacancy_sweeps_today` are set by the callers (`hvac.py:3044-3046`, `:3119-3121`). The only other reader of `vacancy_sweep_done` is `optimization.py:3475`, and it sees the same value.
- **Q2, manual_mode counted as paused: within intent.** `ManualModeSwitch` ON is documented as "disables ALL automation" (`coordinator.py:3183`), so an HVAC sweep of a manual-mode room would be the stronger violation. Keep it, and state it in the README.
- **Unpause adoption (§5) is correct.** A physically-on fan with no cooldown is adopted with a manual-ON hold (`hvac_fans.py:741-825`).

**R1 (HIGH, scope): F3 sleep-onset is occupancy-driven and its room-tier twin is already paused.**
- `_sleep_onset_activation` is documented as "warm, occupied bedrooms" and passes `occupied=room_cond.occupied` (`hvac_fans.py:986-993`, ~`:1083`).
- The room-tier sleep-onset (`automation.py:2810`) is already gated by pause. Excluding F3 therefore makes the outcome depend on Fan Mode: a paused Room-temperature bedroom gets no sleep-onset fan, while a paused Follow-thermostat bedroom does.
- It is also the one paused-room fan ON the audit observed (Master Bedroom, 10-11 22:00).
- **Fix:**
  - In the F3 eligibility loop, right after the G3 `_is_room_hvac_managed` skip (~`hvac_fans.py:1036`), add `if room_automation_paused(...): continue`.
  - Flip the scope-fence test to `test_sleep_onset_skips_paused_room`.
- **Operator confirm needed**, because §0 says F3 was told as excluded. The verbatim ruling ("fans automation based on occupancy") covers it.

**R2 (MED, a fan left ON with nothing to turn it off).** F1 is the OFF discharge for every HVAC-tier fan ON. Gating F1 while leaving ON writers ungated leaves those fans ON with no OFF:
- F3 ON: nothing turns it off while the room is paused.
- F4 `_activate_zone_fans` (`hvac_predict.py:1440`) ON, then the pre-arrival clears as `arrived` (`hvac.py:~7298-7305`, no de-fan on that branch). The fan runs until unpause.

**Fix.** Replace the fuzzy "occupancy-based" boundary with a whitelist invariant that a reviewer can check by grep:
- **INV-P':** in a paused room, no HVAC-tier writer actuates a fan, except:
  - `_stop_all_fans_safety`;
  - `turn_off_all_managed`;
  - the recheck restore discharge.
- Gate F4 activate per room. Also gate `_deactivate_zone_fans` (`hvac.py:7375`) per room: with activate gated it has nothing of its own to undo, and ungated it could turn off a person's fan.
- Fans that URA lit BEFORE the pause stay ON until unpause. That is acceptable per the ruling ("I just didn't want it turning off…"). Say so in §5 and in the README.
- Scope stays one coherent set: the same predicate at 2 more sites, and still Tier 2.

**R3 (HIGH, INV-Z false as written): pausing changes occupancy through D2.**
- The paused-room `room_paused` veto also flips `is_recheck_eligible` (`presence_fan_recheck.py:462`). D2 then demotes, which sets `data[STATE_OCCUPIED]` False (`coordinator.py:~4300-4430`).
- HVAC reads that value (`hvac_zones.py` `data.get("occupied")`, STATE_OF_PLAY §9c/C24). So pausing a room CAN change `hvac_occupied`, the zone rollup and the retreat.
- Plan §2 says "Occupancy is unchanged" and §3 says "It does feed HVAC `hvac_occupied`". These contradict each other.
- The harm is real, not theoretical: Kitchen's 6 `recheck_pause` probes in 7 days were all `occupied_confirmed`. Under the change, those episodes become D2 demotions once D2's bar is met (fan on, mmwave sole, PIR stale ≥ 2× timeout). That can retreat zone_3 with a person cooking.
- **Options:**
  - **(a) Accept.** This is the same outcome Fan Mode Off and `room_disabled` rooms already get, so it is not a new class.
  - **(b) Exempt the inert path from the paused veto.** REJECTED: D2 then defers forever, because the recheck never arms. That is the FAN-RECHECK-D2-DEADLOCK-1 class, and fan noise would hold the room occupied indefinitely.
- **Fix:**
  - Restate INV-Z as: "byte-identical EXCEPT via the documented D2 backstop for paused rooms whose occupancy is radar-sole with the fan running".
  - Add a test pinning that D2 fires for a paused room, so a later change cannot silently reverse it.
  - Add a one-line operator note on the trade: the 150 s fan-off probe is removed, and the cost is a possible early vacancy under D2's high bar.
  - Planner default is (a). Operator can veto.

**R4 (MED, D3 release must be LEVEL, not edge).**
- `_set_fan_state` records `is_on` (`hvac_fans.py:~933`). A mid-flight recheck restore (which the plan keeps ungated) re-sets `is_on=True` after an edge-triggered release, and so would any whitelisted writer.
- With an edge-triggered release:
  1. A person who turns that fan off while the room is paused leaves stale tracking.
  2. On unpause, the external-off sync (`hvac_fans.py:~680`) books a fake 1 h `manual_off_cooldown`.
- That contradicts D3's own "a paused room's manual fan use opens no cooldown". An edge-triggered release also needs a new per-room "was paused" field.
- **Fix:**
  - Clear `is_on`/`trigger`/`speed_pct`/`last_on_time`/`vacancy_detected_time` on EVERY paused tick. It is idempotent and writes nothing.
  - Log INFO only on the edge, or use DEBUG.
  - Extend `test_fan_controller_paused_release_no_write`: pause → mid-flight restore → person turns the fan OFF → unpause → assert no cooldown is booked.

**R5 (MED, Live criteria do not discriminate, and are soak-shaped).**
- The D2 baseline is 3 in 7 days, so the expected count in 72 h is about 1.3. Seeing 0 cannot tell "gated" from "no event happened". "For 72 h" is also a watch window (No-Soak).
- **Replace with a one-shot query run at disposition time that finds positive evidence:**
  - a zone `climate_write reason=vacant_past_grace` row, AND
  - at that second a configured light of a paused room in that zone read `on` in the recorder, AND
  - that light has no URA-stamped on→off within 5 s.
  - That shows the sweep ran and the paused room survived it.
- **Fans:** `room_paused` veto counter > 0 (already in the plan), plus 0 `temp_hvac`/`sleep_onset`/`recheck_pause` rows for paused rooms, plus the unpaused-room companion that is already listed.
- Promote the sweep skip line from DEBUG to INFO, rate-limited to once per room per sweep. Journald is not retrievable on the host (audit §5), so a DEBUG line can never be cited.

**R6 (LOW).** §6: add F3 and F4 as gated rows after R1/R2. The table's "NO (house-state, operator scope)" for F3 is wrong on the facts (R1).

**Scope fence:** no mission creep found. R1 and R2 add 3 call sites of the same predicate. There is no new knob or state, and the tier is unchanged (Tier 2, with build review elevated to 3 framings as §8 recommends; framing B must own R3).

**Verdict: FIX-PLAN.**
- Fold R1 to R6 into §2, §4, §5 and §6.
- Get the operator's one-line confirmation on R1 (F3 in) and R3 (accept the D2 backstop).
- Then the plan is SHIP-TO-BUILD without another review round.
