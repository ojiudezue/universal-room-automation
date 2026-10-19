# PLANNING: paused rooms stop occupancy-driven lights and fans (HVAC tier + fan recheck)

**Status: READY FOR BUILD (2026-10-19).** Plan review (Tier 2, 2026-10-18) returned FIX-PLAN with R1–R6. All six are folded into the body below (disposition table in §10). Both operator questions are answered (§0). The reviewer's verdict was "SHIP-TO-BUILD without another review round" once folded.

Card: ROOM-OVERRIDE-SWITCH-FORGOTTEN-1 (`docs/planning/kanban.data.yaml`). Audit: `docs/planning/AUDIT_paused_rooms_light_fan_paths_2026_10_18.md` (read in full).
Base: `develop` at `ba7a6fa3e` (2026-10-19; every site line below re-verified on this commit; the first draft used `f9fb1f5ba`).
Read first: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` + `docs/architecture/SENSOR_FLEET_CLASSES.md` were read COMPLETELY for this finalisation. Nothing in the HVAC §10 or presence §10 ledger is re-asserted here.

## 0. Operator ruling (the spec) and decisions

- **2026-10-18, verbatim:** "Paused rooms should stop with lights and fans automation based on occupancy. Blinds down, house state, venting are fine. I just didn't want it turning off lights when paused."
- **10-17 answer (superseded):** "Paused rooms should be inert". Kept only so nobody widens scope back to it.

**Operator answers 2026-10-19 (both YES; binding):**
1. **Stop ALL HVAC-side fan automation in paused rooms**, including F3 sleep-onset fan ON and F4 pre-arrival fans (activate AND deactivate). Resolves R1 and R2.
2. **Accept that a paused room can still be marked vacant by D2 demotion**, so its zone's HVAC can retreat. This is a non-goal: do not block it. Resolves R3, option (a).

**Scope after the answers.** In a paused room, these HVAC-tier / presence writers are gated on the room Automation switch:
- **L1:** HVAC zone vacancy sweep (lights, night lights, fans).
- **F1:** HVAC comfort fans (`FanController.update`: temp on/off/speed and external-change adoption).
- **F2:** fan recheck arm/pause.
- **F3:** HVAC sleep-onset fan ON.
- **F4a / F4b:** pre-arrival fans ON (`hvac_predict._activate_zone_fans`) and OFF (`hvac._deactivate_zone_fans`).

Not gated (operator: fine, or safety/discharge):
- covers; AI and house-state chained rules; humidity venting;
- safety stops (`_stop_all_fans_safety`), the kill switch `turn_off_all_managed`;
- the fan-recheck restore discharge (`restore_after_recheck`);
- the room tier (already gated) and the Away leave-on sweep (already gated, 2026-09-30 ruling).

**Decided:** `manual_mode` ON counts as paused (it is "disables ALL automation", `coordinator.py:3183`; that is how the predicate already behaves). State it in the README.

## 1. Institutional context verified

**Config-first check.** No setting fixes this.
- **Zone sweep switch** (`switch.ura_hvac_coordinator_zone_sweep`): zone-wide; turning it off also stops the sweep in unpaused rooms of the zone. Not equivalent.
- **Fan Mode = Off per paused room** (`select.<room>_fan_mode`, `const.fan_owner` at `const.py:1296`): stops F1–F4 but is rejected — a second knob to keep in sync with the pause switch, unpausing does not restore it, and it does nothing for L1 lights (the operator's actual complaint).
- **Conclusion:** code is warranted. The knob is the room Automation switch the operator already uses.

**Prior-art scan, REUSE or BUILD per piece:**

| Piece | Verdict | Evidence |
|---|---|---|
| "Is this room paused?" | **REUSED** `RoomCoordinator._is_automation_enabled` `coordinator.py:3181` (manual_mode ON → disabled; `automation` switch off → disabled; switch missing → enabled). Switch `AutomationSwitch` `switch.py:5103`. | Consumers today: `coordinator.py:5235`, `automation.py:890`, `actuator_reconciler.py:544`. `grep -rn _is_automation_enabled domain_coordinators/` = 0 hits (re-run 2026-10-19). |
| Shared predicate `room_automation_paused(room_coord) -> bool` | **NEW** (~10 lines, `const.py` next to `fan_owner` `const.py:1296`, the existing cross-tier duck-typed ownership home already imported by `hvac_fans`, `hvac`, `hvac_predict` and `presence_fan_recheck`). Six call sites in four modules; each would otherwise hand-roll a private-method call plus exception handling. | Grepped `const.py`, `hvac.py`, `hvac_fans.py`, `hvac_predict.py`, `presence_fan_recheck.py`, `fan_veto.py` for `paused`, `automation_enabled`, `room_automation`: nothing equivalent. `fan_veto.py` is house-AWAY-specific — wrong home. |
| Room coordinator lookup, `hvac.py` / `hvac_predict.py` | **REUSED** `HVACCoordinator._get_room_coordinator` `hvac.py:6942`; already called in the sweep loop `hvac.py:6730`, F4a loop `hvac_predict.py:1451`, F4b loop (`hvac.py:7375` + 17) | — |
| Room coordinator lookup, recheck | **REUSED** `FanRecheckManager._room_coord_for` `presence_fan_recheck.py:1341`; `_evaluate_eligibility` (`:514`) and `_still_armed_eligible` (`:1213`) already receive `room_coord` | — |
| Room coordinator lookup, FanController | **NEW small accessor** `FanController._room_coord(room_name)` with the same shape as `_room_coord_for` (entry scan → `hass.data[DOMAIN][entry_id]`). | `grep "_get_room_coordinator\|_room_coord" hvac_fans.py` = 0. FanController resolves config only (`_live_room_merged` `hvac_fans.py:1209`). |
| F1/F3 "stop managing, never actuate" semantics | **REUSED** the release branch of `_is_room_hvac_managed` (`hvac_fans.py:1245-1287`: clears `is_on` / `trigger` / `speed_pct` / `last_on_time` / `vacancy_detected_time`, writes nothing) and its hand-back adoption. Doctrine: HVAC STATE_OF_PLAY §4.2b "Leaving Follow thermostat RELEASES tracking and never turns the fan off". | — |
| F2 veto shape | **REUSED** the `sink.veto(room_name, "<reason>")` ladder (`room_disabled` at `presence_fan_recheck.py:546` is the sibling) + arm-delay twin `_still_armed_eligible`. New veto reason string `room_paused`. | — |
| Per-room skip shape (sweep, F4a, F4b) | **REUSED** the existing per-room `continue` after the coordinator-None check in each loop. | — |
| New knob | **None.** The room Automation switch is the knob; no behavioural number is introduced. | — |

Prior plans/docs consulted: the audit; `PLANNING_fan_noise_running_rejection.md` Rev 2 (C1a `leave_off`), skimmed; HVAC STATE_OF_PLAY §3.2 (retreat-gate consumers), §4.2b (Fan Mode as the one rule), §9c (Override Occupied/Vacant → `hvac_zones` reads `data.get("occupied")`), C24; PRESENCE STATE_OF_PLAY §4.5 (room switches), §6 items 2–3 (D2, recheck); card bodies `verify_2026_10_18_overnight`, `operator_answer_2026_10_17`, `operator_answer_2026_10_18`, `disposition_2026_10_15_overnight`.

Code read (on `ba7a6fa3e`): `hvac.py` 2451, 3025-3047, 3105-3125, 6585-6700 (safety stop), 6713-6880 (`_execute_vacancy_sweep`), 6942, 7255-7470 (pre-arrival clear + `_deactivate_zone_fans`); `hvac_fans.py` 532-560, 569-960 (`update`), 986-1130 (`_sleep_onset_activation`), 1209-1290, 1690-1760, 2079-2330; `hvac_predict.py` 700-705, 1440-1600; `presence_fan_recheck.py` 462-551, 1213-1245, 1341-1347, 1622-1660; `coordinator.py` 3170-3200, 4360-4390 (D2 defer), 5225-5345, 5726-5760; `automation.py` 857-895, 2770-2810, 4464-4500, 4672; `switch.py` 5405-5475; `aggregation.py` 1472-1535.

## 2. Falsifiable invariants

- **INV-P' (whitelist gate; replaces the first draft's INV-P, per R2):** while a room's `_is_automation_enabled()` is False, **no HVAC-tier or presence writer actuates that room's configured lights, night lights or fans, except** (i) `_stop_all_fans_safety` (`hvac.py:6585`, via `_safety_stop_one_fan`), (ii) `turn_off_all_managed` (`hvac_fans.py:532`, called from `hvac.py:2451`), and (iii) the recheck restore discharge (`restore_after_recheck` `hvac_fans.py:2138` → `_restore_after_recheck_body` → `_set_fan_state` `:2324`). This holds in every reachable path: row-1 vacant_past_grace and D6 stale-occupancy sweeps, any house state, either Fan Mode, pre-arrival begin/timeout, sleep onset.
  - Checkable by grep: every writer in §6 is either gated or one of the three whitelisted.
- **INV-Z (no retreat drift, RESTATED per R3):** for any zone, the S1 preset writes, `climate_write` rows, `zone.vacancy_sweep_done` and `_vacancy_sweeps_today` are byte-identical whether or not some of the zone's rooms are paused, **EXCEPT via the documented D2 backstop**: a paused room whose occupancy is radar-sole with its fan running may be demoted to vacant by D2 (because `room_paused` makes it recheck-ineligible, so D2 is no longer deferred), which feeds `hvac_occupied` and can let the zone retreat. Operator-accepted 2026-10-19. **Second exception (review B-M1, 2026-10-19):** a paused room also loses the fan recheck's VACATED release (the `room_paused` veto means no probe), so in a paused room without a fan-immune witness (Media, Guest Bedroom 1, Guest Bedroom 2 today: MS600 radar-derived motion bits only, D2 fails closed) a running fan can hold the room, and so its zone, occupied until the 4 h stuck-sensor rule or the P24 max-occupancy failsafe fires. This is the opposite direction to the D2 backstop (it holds rather than retreats). Accepted consequence of the operator ruling that a probe must not turn a person's fan off (review B-M1, 2026-10-19).
  - Why the sweep part holds: `_execute_vacancy_sweep` returns None and nothing reads its result; `vacancy_sweep_done` / `_vacancy_sweeps_today` are set by the callers (`hvac.py:3044-3046`, `:3119-3121`); the only other reader of `vacancy_sweep_done` is `optimization.py:3475`, which sees the same value.
  - Outside the D2 backstop, a paused room's occupancy computation is unchanged (it still computes `STATE_OCCUPIED`, `coordinator.py` else-branch after `:5235`).
- **INV-N (no-op path):** with no room paused, every gated site behaves byte-identically to today. The predicate is one extra read and returns False.

**Falsifiers a reviewer should try:**
- A paused room in a zone where the D6 branch sweeps.
- A paused room whose coordinator is None (already skipped today; unchanged).
- `manual_mode` ON with `automation` ON (must count as paused).
- A room paused while a recheck is PAUSED (restore must still run, §4 D3).
- A paused room's fan restored ON by a mid-flight recheck, then turned off by a person, then the room unpaused (R4: no fake cooldown).
- Pre-arrival begins for a zone with a paused room, then clears `arrived` (R2: paused room's fan never turned on, so nothing is left running).
- Pre-arrival timeout `_deactivate_zone_fans` over a paused room whose fan a person turned on (must not be turned off).
- Sleep onset with a paused, warm, occupied, Follow-thermostat bedroom (R1: no fan ON).
- Unpause inside a vacancy where `vacancy_sweep_done` is already True (§5, no catch-up).

## 3. Producer / consumer

- **Producer: `_is_automation_enabled`** (`coordinator.py:3181`). It reads the room's `manual_mode` and `automation` switch states through `_get_room_switch_state` / `_resolve_room_switch_entity_id` (`coordinator.py:3028-3074`, registry `unique_id` lookup, cached; the v5.103.48 fix — PRESENCE §10 #4).
  - Dependencies are healthy: the 20 rooms paused live (audit §3a) read `off` continuously, restored across restarts.
  - Missing switch → enabled (fail-open, today's behaviour). An exception inside the wrapper also → not paused. **Not fail-open (review A-L1):** a switch that reads `unavailable` / `unknown` (room reload, entity re-create) reads as PAUSED, because `_get_room_switch_state` tests `state == "on"` (`coordinator.py:3179`); this is the room tier's own pre-existing semantics. Fail-open is acceptable because the failure mode is today's behaviour, not a new harm.
- **Consumers after the change (all trust/actuation decisions):**
  - Existing: `coordinator.py:5235`, `automation.py:890`, `actuator_reconciler.py:544`.
  - New (via `room_automation_paused`): sweep loop `hvac.py` ~6731; F1 loop `hvac_fans.py` ~649; F3 loop `hvac_fans.py` ~1036; F4a loop `hvac_predict.py` ~1453; F4b loop `hvac.py` ~7394; recheck `_evaluate_eligibility` ~546 and `_still_armed_eligible` (`:1213`).
- **Secondary consumer (R3, operator-accepted):** `is_recheck_eligible` (`presence_fan_recheck.py:462`, inert sink) feeds the room coordinator's D2 mmwave-fan demotion defer (`coordinator.py:4372-4381`).
  - A paused room becomes ineligible, so D2 is no longer deferred and fires as the backstop once its bar is met (fan on, radar sole, PIR stale ≥ 2× timeout; Sleep/Waking/Home-Night bedrooms exempt — PRESENCE §6 item 2).
  - Same outcome Fan-Mode-Off and `room_disabled` rooms already get. Exempting the inert path instead was REJECTED: D2 would defer forever because the recheck never arms (FAN-RECHECK-D2-DEADLOCK-1 class).
  - **Operator trade (README one-liner):** in a paused fan room, the 150 s fan-off probe no longer runs; the cost is a possible earlier vacancy under D2's high bar (Kitchen's 6 `recheck_pause` probes in 7 days were all `occupied_confirmed`). Lights are unaffected either way (the room tier is paused; the sweep skips the room).

## 4. Deliverables

### D1. Shared predicate `room_automation_paused`
In `const.py` next to `fan_owner`: `def room_automation_paused(room_coord) -> bool`.
- True only when `room_coord` exposes a callable `_is_automation_enabled` that returns exactly `False`.
- `None`, a missing attribute or an exception → False. Never raises.

**Acceptance**
- **Test:** `test_paused_room_gates.py::test_predicate_truth_table` — coordinator None; no method; automation off; manual_mode on; both on; raises → False.
- **Verify:** `grep -rn "_is_automation_enabled" custom_components/universal_room_automation/domain_coordinators/` = 0 hits. The new sites call only `room_automation_paused`.

### D2. L1: zone vacancy sweep skips paused rooms
In `_execute_vacancy_sweep` (`hvac.py:6728` loop), right after the coordinator-None `continue` (`:6731`), add `if room_automation_paused(coordinator): <log>; continue`.
- Lights, night lights and fans are all skipped for that room (both emit sites `:6773` and `:6869` sit after it).
- **Log (R5):** INFO, not DEBUG — one line per paused room per sweep invocation ("vacancy sweep: <room> paused — skipped"). A sweep runs once per zone vacancy, so this is naturally bounded; no extra rate-limit state.
- No change at the two call sites, to `vacancy_sweep_done`, or to `_vacancy_sweeps_today`.

**Acceptance**
- **Test:** `test_sweep_skips_paused_room_lights_and_fans` — zone with A (paused) and B (enabled), both with lights on and HVAC-owned fans. A gets 0 `turn_off` calls; B gets them all. Discriminates against a zone-level skip (B would get 0) and no gate (A would get calls).
- **Test:** `test_sweep_paused_room_d6_branch` — same assertion through the D6 caller (`hvac.py:3119`).
- **Test:** `test_sweep_manual_mode_counts_as_paused` — `manual_mode` ON, `automation` ON → A skipped.
- **Test:** `test_zone_retreat_unchanged_with_paused_room` (INV-Z, occupancy held fixed) — same tick run twice (A paused, then enabled): S1 preset write, `vacancy_sweep_done` and the sweep counter are equal; only the `turn_off` set differs.
- **Live (one-shot query at disposition, R5):** find positive evidence, not absence: a zone `climate_write reason=vacant_past_grace` row for which, at that second, a configured light of a paused room in that zone read `on` in the recorder AND that light has no URA-context (`context_parent_id` URA ULID, `ura_context.py:55`) on→off within 5 s; plus the INFO skip line in `home-assistant.log` naming the room if retrievable. Under a missing gate the same query returns a URA-stamped off; under "no sweep happened" it returns no qualifying `climate_write` row — distinguishable from a pass. If no qualifying row exists at disposition, the criterion is "not yet exercised" (in-suite proof only), not PASS.

### D3. F1 HVAC comfort fans + F2 fan recheck skip paused rooms

**F1.** In `FanController.update`'s per-room loop (`hvac_fans.py:643`), right after the G2 `_is_room_hvac_managed` skip (`:648-649`) and BEFORE the recheck suppress-until handshake and the external-change sync, add `if room_automation_paused(self._room_coord(room_name)): self._release_room_tracking(room_name, room_fan, reason="room_paused"); continue`.
- **`_release_room_tracking` (new private helper, factored out of the `_is_room_hvac_managed` release branch so there is ONE copy; that branch calls it too).** It clears `is_on`, `trigger`, `speed_pct`, `last_on_time`, `vacancy_detected_time`. It writes nothing. It must NOT touch `fan_recheck_suppress_until`, the manual-ON hold fields, or the manual-off cooldown ledger.
- **LEVEL, not edge (R4):** the release runs on EVERY paused tick (idempotent). This is required because the whitelisted restore discharge re-sets `is_on=True` via `_set_fan_state`; an edge-only release would leave stale tracking that, after a person turns the fan off and the room is unpaused, the external-off sync (`hvac_fans.py` ~680) books as a fake 1 h `manual_off_cooldown`. No per-room "was paused" field is added.
- **Log:** INFO on the transition into paused only (detected as "tracking was non-empty before the clear", or `is_on`/`trigger` set) — otherwise DEBUG. No new state.
- The `_set_fan_state` chokepoint is NOT gated (the whitelisted writers route through it).

**F2.** In `_evaluate_eligibility`, right after the `room_disabled` veto (`presence_fan_recheck.py:546`), add `if room_automation_paused(room_coord): return sink.veto(room_name, "room_paused")`. The same check goes into `_still_armed_eligible` (`:1213`), so an ARMED (not yet paused) room disarms on its next check.
- A recheck already PAUSED when the operator flips the switch is NOT cut short. It completes, and its restore is a discharge that must run: suppress-until clear, room-tier `note_recheck_restore`, fan back to its snapshot (or left off on VACATED, C1a). Gating the restore would strand the fan off — excluded.
- Because `is_recheck_eligible` reads the same ladder, it returns False for a paused room (the R3 side effect in §3, accepted).

**Acceptance**
- **Test:** `test_fan_controller_skips_paused_room` — paused room, HVAC-owned fans, warm, vacant past hold → 0 `_set_fan_state` calls; enabled twin gets its OFF.
- **Test:** `test_fan_controller_paused_release_level_no_write` (R4) — pause a room whose fan is tracked ON: tracking cleared, no service call. Then: mid-flight recheck restore writes ON (`is_on=True`) → next paused tick clears it again → person turns the fan OFF → unpause → next `update()` books NO `manual_off_cooldown`. Discriminates against an edge-only release (which books the cooldown).
- **Test:** `test_release_helper_single_copy` — Fan-Mode hand-back and paused release produce identical tracking state (both call `_release_room_tracking`).
- **Test:** `test_fan_recheck_vetoes_paused_room` — eligibility False with veto counter `room_paused`; `is_recheck_eligible` False; `_still_armed_eligible` False.
- **Test:** `test_fan_recheck_paused_mid_flight_restores` — room paused while the recheck is PAUSED; the restore still writes the snapshot state. Discriminates against gating the restore (fan stays off).
- **Test (R3 pin):** `test_paused_room_d2_backstop_not_deferred` — paused room, fan on, radar-sole, PIR stale past the D2 bar, house `home_day`: the coordinator's D2 defer at `coordinator.py:4372-4381` does NOT defer (recheck ineligible) and the room demotes to vacant. Pins the operator-accepted trade so a later change cannot silently reverse it (or silently create the deadlock).
- **Live (one-shot at disposition, R5):** (a) `fan_recheck` veto counters show `room_paused` > 0 for a paused fan room (Kitchen is the likeliest); (b) `ura_activity_log` has 0 `fan_on`/`fan_off` rows with `trigger` in {`temp_hvac`, `sleep_onset`, `recheck_pause`, pre-arrival triggers} for rooms paused at that row's time (join on the room's `switch.<room>_automation` recorder state at the row timestamp); (c) discriminating companion: an unpaused fan room (e.g. Jaya Bedroom by day) still shows `temp_hvac` rows, proving the controller is not dead. (a) alone discriminates "gated" from "no event" — if (a) is 0 because no qualifying condition arose, mark "not yet exercised", not PASS.

### D4. F3 sleep-onset fan ON skips paused rooms (R1, operator answer 1)
In `_sleep_onset_activation`'s eligibility loop (`hvac_fans.py:1030`), right after the G3 `_is_room_hvac_managed` skip (`:1036`), add `if room_automation_paused(self._room_coord(room_name)): continue`. No release here (F1's level release owns tracking).
- Rationale: F3 is occupancy-driven ("warm, occupied bedrooms", passes `occupied=room_cond.occupied`), and its room-tier twin `_maybe_sleep_onset_activate` (`automation.py:2810`) is already paused. Without this, the outcome would depend on Fan Mode. It is also the one paused-room fan ON the audit observed (Master Bedroom, 10-11 22:00).

**Acceptance**
- **Test:** `test_sleep_onset_skips_paused_room` — paused, warm, occupied, Follow-thermostat bedroom → no `_set_fan_state` ON; enabled twin bedroom → ON. (Replaces the first draft's scope-fence test, which asserted the opposite.)
- **Live:** covered by D3 Live (b) (`sleep_onset` trigger).

### D5. F4 pre-arrival fans skip paused rooms (R2, operator answer 1)
- **F4a:** in `_activate_zone_fans` (`hvac_predict.py:1440`; per-room loop `:1450`), right after the coordinator-None `continue` (`:1452-1453`), add `if room_automation_paused(coordinator): continue`. Both emit sites (`:1559`/`:1583`/`:1597`) sit after it.
- **F4b:** in `_deactivate_zone_fans` (`hvac.py:7375`; per-room loop `:7389`), right after the coordinator-None `continue` (`:7393-7394`), add the same check. With F4a gated it has nothing of its own to undo in a paused room, and ungated it could turn off a person's fan (emit `:7463`).
- Callers unchanged: `hvac_predict.py:703` (activate), `hvac.py:7320` (timeout) and `:7357` (pre-arrival end) (deactivate).
- Consequence (R2 closed): F1 is the OFF discharge for every HVAC-tier fan ON; with F3 and F4a gated, no HVAC-tier ON reaches a paused room, so no fan is left running with nothing to turn it off. The `arrived` clear (`hvac.py:7296-7305`, no de-fan) is now harmless for paused rooms.

**Acceptance**
- **Test:** `test_prearrival_activate_skips_paused_room` — zone with A (paused) and B (enabled), both warm with Follow-thermostat fans → A 0 `turn_on`, B gets its ON.
- **Test:** `test_prearrival_deactivate_skips_paused_room` — timeout path over A (paused, fan on by a person) and B (enabled, fan on) → A 0 `turn_off`, B turned off.
- **Live:** covered by D3 Live (b).

### D6. Doc write-back (same build commit)
- **PRESENCE STATE_OF_PLAY:** fan-recheck item 3 gets the `room_paused` veto and the D2-backstop note; §4.5 room switches: "the Automation switch (and Manual Mode) now also gate the HVAC zone sweep, HVAC comfort fans, HVAC sleep-onset, pre-arrival fans and the fan recheck arm; the recheck restore, safety stop and `turn_off_all_managed` are not gated".
- **HVAC STATE_OF_PLAY:** §4.2b, a new bullet listing the gated HVAC-tier sites and the three whitelisted writers; header currency line.
- **Card:** the `verify_2026_10_18_overnight` correction (audit §5).
- **README** (at deploy): the `manual_mode` = paused note; the D2-backstop trade one-liner (§3); "fans URA lit before the pause stay on until unpause" (§5).

**Acceptance**
- **Verify:** both STATE_OF_PLAY docs carry the lines in the build commit.

## 5. Unpause / pre-pause behaviour (decided, with reasons)

- **Fans URA lit BEFORE the pause stay ON until unpause** (or until a person, safety stop or `turn_off_all_managed` turns them off). Acceptable per the ruling ("I just didn't want it turning off…"). README line.
- **Sweep, no catch-up:** `vacancy_sweep_done` is zone-scoped and set once per vacancy. A room unpaused mid-vacancy keeps its lights on until the next zone vacancy, or until the room tier acts on its next occupancy edge or scheduled auto-off.
  - A catch-up needs a per-room "owed sweep" ledger or re-arming `vacancy_sweep_done` on an unpause edge — a new cross-coordinator edge listener (switch → HVAC) on a rare-fire path. Benefit: one late OFF of a light the operator just handed back. Margin does not pay; PARKED. Revival trigger: the operator reports lights left on after unpausing.
- **F1 on unpause:** the next `update()` treats the room like a Fan Mode hand-back (existing path, `hvac_fans.py:741-825`): a physically-on fan is adopted with a manual-ON hold, not forced off (this includes a fan URA itself lit before the pause, or one the recheck restore re-lit: it stays on for up to one manual-ON hold instead of being temperature-managed — review B-L2); an off fan resumes temperature logic. Because the release is level (R4), tracking is clean at unpause, so no fake cooldown. No new code.
- **F2 / F3 / F4 on unpause:** eligibility re-opens on the next tick / next sleep onset / next pre-arrival, with no state to restore.

## 6. Emission/decision-site enumeration (re-run 2026-10-19 on `ba7a6fa3e`)

Commands run:
- `grep -n "turn_off\|turn_on\|_set_fan_state(" domain_coordinators/{hvac,hvac_fans,hvac_predict,presence_fan_recheck}.py`, each hit mapped to its enclosing function.
- `grep -rlE "\"turn_(on|off)\"|'turn_(on|off)'"` over the package → `actuator_reconciler.py`, `aggregation.py`, `automation.py`, `const.py`, `coordinator.py`, `domain_coordinators/{energy,hvac,hvac_fans,hvac_predict,notification_manager}.py`, `switch.py`; non-HVAC hits mapped to functions.
- Callers of every room-tier light/fan entrypoint (`handle_occupancy_change`, `handle_temperature_based_fan_control`, `handle_humidity_based_fan_control`, `check_scheduled_auto_off`, `check_auto_off_warning`, `_shared_space_turn_off_all`, `_maybe_sleep_onset_activate`, `handle_away_leave_on_sweep`).

| # | Site (file:line on `ba7a6fa3e`) | Action | Gated? |
|---|---|---|---|
| 1 | `hvac.py:6713` `_execute_vacancy_sweep` (emits `:6773` lights/night lights, `:6869` fans); callers `:3044` row-1, `:3119` D6 | lights/fans OFF | **YES — D2** (inside the function, both callers covered) |
| 2 | `hvac_fans.py:569` `update` → per-room loop `:643` → `_set_fan_state` `:920` | temp fan on/off/speed + external-change adoption | **YES — D3 F1** (level release) |
| 3 | `hvac_fans.py:986` `_sleep_onset_activation` (called `:956`) → `_set_fan_state` `:1121` | fan ON | **YES — D4** (was NO in draft; R1/R6) |
| 4 | `hvac_predict.py:1440` `_activate_zone_fans` (called `:703`) → emits `:1559`/`:1583`/`:1597` | pre-arrival fan ON | **YES — D5 F4a** (was NO; R2/R6) |
| 5 | `hvac.py:7375` `_deactivate_zone_fans` (called `:7320` timeout, `:7357` end) → emit `:7463` | pre-arrival fan OFF | **YES — D5 F4b** (was NO; R2/R6) |
| 6 | `presence_fan_recheck.py` `_evaluate_eligibility` `:514` / `_still_armed_eligible` `:1213` → `_fan_pause` `:1622` → `pause_for_recheck` `hvac_fans.py:2079` → `_set_fan_state` `:2127` | recheck fan OFF probe | **YES — D3 F2** (at arm) |
| 7 | `restore_after_recheck` (`presence_fan_recheck.py:1647` → `hvac_fans.py:2138` → `_restore_after_recheck_body` `:2176` → `_set_fan_state` `:2324`) | restore | NO — whitelisted discharge (INV-P' iii) |
| 8 | `hvac.py:2451` → `turn_off_all_managed` `hvac_fans.py:532` (`:541`) | fan OFF | NO — kill switch (INV-P' ii) |
| 9 | `hvac.py:6585` `_stop_all_fans_safety` → `_safety_stop_one_fan` `:6626` (`:6644`/`:6672`/`:6687`) | fan OFF | NO — safety (INV-P' i) |
| 10 | `hvac_fans.py:1690` `_emit_fan_state` (`:1702-1721`) | inner emit of `_set_fan_state` | n/a — only reached through rows 2/3/6/7/8 |
| 11 | Room tier `coordinator.py:5235` block: `handle_occupancy_change` `:5241`/`:5311`, `handle_temperature_based_fan_control` `:5326` (→ `_maybe_sleep_onset_activate` `automation.py:2810`), `check_scheduled_auto_off` `:5337` (→ `_shared_space_turn_off_all` `automation.py:4492`), `check_auto_off_warning` `:5338` | lights/fans | already gated |
| 12 | `coordinator.py:5726` `_delayed_exit_verify` → `handle_occupancy_change(False)` `:5751`, scheduled at `:5284` inside the gated block | light OFF retry 3 s after a gated exit | already gated at schedule time; see §7 residual |
| 13 | `automation.py:857` `handle_away_leave_on_sweep` (gate `:890`); reconciler `actuator_reconciler.py:544` | lights/fans | already gated |
| 14 | Humidity `coordinator.py:5421`; covers (`check_timed_cover_*`); AI/chained `coordinator.py:1153` `_execute_rule_action` (`:1239`/`:1250`) | various | NO — operator: fine |
| 15 | `switch.py:5411`/`:5458` `RoomLightsSwitch` turn_on/off | lights | NO — a person's explicit command, not automation |
| 16 | `aggregation.py:1472` `_flash_light`; `notification_manager.py`; `energy.py`; `const.py:1142-1144` (constants) | alert lights / NM / energy loads | NO — not room-occupancy light/fan writers |

The builder MUST re-run the three commands above before the build; any new fan or light writer reached from a per-room occupancy decision is a finding.

## 7. Non-goals
- No change to `turn_off_all_managed`, safety stops, the recheck restore discharge, humidity venting, covers, AI/house-state chained rules, the Away leave-on sweep (already gated), or the room tier.
- **No block on D2 demotion of a paused room** (operator answer 2): occupancy computation, `hvac_occupied`, zone retreat, S1 and the borrow primitive are not changed; the D2 backstop is accepted and pinned by a test.
- No unpause catch-up (§5, parked). No turn-off of fans URA lit before the pause.
- No forgotten-pause reminder (separate optional item on the card).
- No new knob, no new switch, no DB/schema change, no new activity-log action. INFO/DEBUG lines and the `room_paused` veto counter are enough.
- **CLOSED in the build (operator 2026-10-19, ambiguity #1):** `_delayed_exit_verify` now re-reads `_is_automation_enabled()` after its 3 s delay and skips the retry (`skipped_paused`); test `test_delayed_exit_verify_skips_retry_when_paused`. The text below is the superseded plan position.
- **Accepted residual (row 12):** `_delayed_exit_verify` retries an exit 3 s after a gated tick without re-reading the switch. Reachable only if the operator pauses the room within 3 s of a real exit edge whose lights did not go off; a retry then is the same exit the room tier was already executing. Not gated; revisit only if observed.
- Guest Bedroom 2 10-16 unattributed OFF: not investigated here (audit §5).

## 8. Tier

**Tier 2, build review elevated to 3 framing-disjoint reviews** (CLAUDE.md standing policy: cross-coordinator presence ↔ HVAC ripple). Six call sites of one small predicate across four modules plus one factored helper; no state machine threaded, no cost/safety value, no new state.
- **A — per-site correctness + fail-open:** each of the six sites, the predicate truth table, the level release's field list (must not touch suppress-until / hold / cooldown), log levels.
- **B — integration / state-machine integrity; OWNS R3:** INV-Z as restated (D2 backstop is the only drift path; no other occupancy change), recheck mid-flight restore discharge, R4 level-release × whitelisted restore × unpause cooldown, pre-arrival `arrived`/timeout paths, INV-N byte-identical no-op.
- **C — per-site mutation (`ura-reviewer-mutation`):** delete each `room_automation_paused` check in turn (sweep, F1, F3, F4a, F4b, recheck eligibility, still-armed) and make the F1 release edge-only — each mutation must turn a named test RED.

Plan review: done (Tier 2, one adversarial pass, FIX-PLAN → folded here). No further plan review required.

## 9. Test inventory (new file `quality/tests/test_paused_room_gates.py` unless noted)
`test_predicate_truth_table`, `test_sweep_skips_paused_room_lights_and_fans`, `test_sweep_paused_room_d6_branch`, `test_sweep_manual_mode_counts_as_paused`, `test_zone_retreat_unchanged_with_paused_room`, `test_fan_controller_skips_paused_room`, `test_fan_controller_paused_release_level_no_write`, `test_release_helper_single_copy`, `test_fan_recheck_vetoes_paused_room`, `test_fan_recheck_paused_mid_flight_restores`, `test_paused_room_d2_backstop_not_deferred`, `test_sleep_onset_skips_paused_room`, `test_prearrival_activate_skips_paused_room`, `test_prearrival_deactivate_skips_paused_room`.

Tests must drive the production functions with a room coordinator whose `_is_automation_enabled` is real or a minimal object exposing it (not a monkeypatched `room_automation_paused`), so framing C's per-site deletions are observable.

## 10. Plan review 2026-10-18 — disposition (findings folded)

Reviewer (ura-planner, Tier-2 adversarial) read HVAC STATE_OF_PLAY completely, the audit and the presence fan-recheck section; re-ran greps on `f9fb1f5ba`. Verified as stated: the room tier is fully gated (incl. `_maybe_sleep_onset_activate` via `automation.py:2810`); no other file is a room-occupancy light/fan writer; INV-Z's sweep part holds; `manual_mode` = paused is within intent; unpause adoption is correct.

| Finding | Severity | Disposition |
|---|---|---|
| R1 — F3 sleep-onset is occupancy-driven; its room-tier twin is already paused | HIGH | FOLDED: D4; operator answer 1 (YES); scope-fence test flipped to `test_sleep_onset_skips_paused_room` |
| R2 — F1 is the only OFF discharge; ungated F3/F4 ONs strand fans | MED | FOLDED: INV-P' whitelist (§2); D5 gates F4a and F4b; §5 "fans lit before pause stay on" |
| R3 — INV-Z false: `room_paused` → recheck-ineligible → D2 demotes → `hvac_occupied` | HIGH | FOLDED: INV-Z restated with the D2 exception; §3 trade note; `test_paused_room_d2_backstop_not_deferred`; operator answer 2 (accept, option a); framing B owns it (§8) |
| R4 — F1 release must be LEVEL, not edge | MED | FOLDED: D3 F1 level release + `test_fan_controller_paused_release_level_no_write` |
| R5 — Live criteria non-discriminating and soak-shaped | MED | FOLDED: D2/D3 Live rewritten as one-shot positive-evidence queries with "not yet exercised" outcome; sweep skip line promoted to INFO |
| R6 — §6 table wrong for F3/F4 | LOW | FOLDED: §6 rows 3–5 now gated; table re-run on `ba7a6fa3e` |
