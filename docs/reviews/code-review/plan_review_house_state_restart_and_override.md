# Plan review: PLANNING_house_state_restart_and_override.md (Tier 2-DB, one adversarial pass)

Reviewer: ura-reviewer, 2026-09-29. Read-only. HVAC state-of-play doc not re-read (the plan touches HVAC only as a consumer); no §10 claims asserted.

**Verdict: REVISE.** The two HIGH design gaps are F2 (staleness is measured from the last transition, not from shutdown) and F3 (restoring `state_since` removes the dwell protection). F4 (the incident may be driven by zone sleep, not house state) could mean D1 does not fix the 03:01 incident.

## Findings

1. **HIGH: the consumer census counts only signal subscribers. Direct readers of house state are missing, and D1 changes what every one of them sees at boot.**
   - Readers not listed: `hvac.py:1425` boot seed (this is the actual D1 mechanism for HVAC), `energy.py:7378`, `notification_manager.py:3766`, `binary_sensor.py:2204/2243/2339` (away/sleep/guest), `presence.py:1850`, `manager.py:623/808`, `music_following.py:157-173` seed, `optimization.py:2169`, `__init__.py:4311`, `sensor.py:5371/5465/6480`.
   - An indirect effect is also missing. `hvac_override.py:903` `sunset_immune_holds` runs on every house-state signal, so D2 `override_set`/`override_clear` will now sunset arrester immune holds. That is a new behaviour.
   - Override writers are not enumerated: `__init__.py:5690/5695/5698/5709/5711`, `select.py:270/275/278` (the fallback paths call the machine directly), and `presence.py:7613/7621`. Putting the hook inside the machine covers all of them, but the plan must list them and test at least one fallback path.
   - Fix in plan: add a direct-reader table showing restored vs walked behaviour, and add the arrester-sunset effect to Review B's scope.

2. **HIGH: the staleness anchor is wrong for non-graceful restarts.** Saves happen only on change plus `homeassistant_stop` (D1 design). On a crash, watchdog restart or kill, `saved_at` is the time of the last transition.
   - Repro: SLEEP entered at 23:00, watchdog restart at 03:00. `saved_at` is 4 h old, beyond 1800 s, so the machine restores AWAY. That is exactly the incident class, and the restart-storm memory shows non-graceful restarts are real.
   - A `homeassistant_stop` save is also not guaranteed to flush.
   - Fix in plan: a heartbeat save (e.g. `Store.async_delay_save` every N min, with a named knob) so `saved_at` tracks liveness. Or a `final_write` listener plus a heartbeat. State that staleness equals down time.

3. **HIGH: restoring `state_since` removes hysteresis, and it contradicts the plan's own acceptance criterion.** With the original `state_since`, `dwell_seconds` is already past every minimum (`house_state.py:154-176`). The first post-boot inference can therefore transition immediately. The D1 integration criterion ("no signal until presence's normal dwell elapses") cannot pass against this design.
   - Worse: boot-settle suppresses only the dispatch. `transition()` at `presence.py:6626` still mutates the machine before the gate at `:6767`. Repro: restored SLEEP, BLE/census not up at boot, census = 0, so inference proposes AWAY (a valid transition, `house_state.py:74-77`). The machine silently becomes AWAY, HVAC has already seeded SLEEP (`hvac.py:1425`), and no signal ever fires. HVAC and security diverge from house state until the next real transition.
   - Fix in plan: choose one. (a) Set `state_since = now` on restore (re-arm dwell). (b) Hold inference transitions until boot-settle lifts. State the behaviour for a suppressed transition when the machine was restored. Make the integration criterion match.

4. **HIGH: it is not established that house state drove the 03:01 HVAC Sleep-to-Home flip.** D0 itself cites "zones 1-2 Sleep->Home at 03:07". Zone-tracker sleep (`presence.py:927` `set_sleep`, overrides at `:7617-7628`) is not persisted by D1.
   - If HVAC presets key off zone presence mode, D1 alone does not fix the incident.
   - Fix in plan: add a D0 item that traces `command_trail` / `climate_write` at 03:07 to its trigger (house signal or zone mode). Either put zone sleep restore in scope or make it an explicit non-goal. The live criterion must discriminate house-state restore from zone restore.

5. **HIGH: D2 bypasses the boot-settle and observation-mode gates.** The design dispatches straight from the machine hook, while inference dispatch is gated at `presence.py:6767-6787`. Review B mentions this, but the Design section does not.
   - The D2 DB criterion ("one `house_state_transition` row per set/clear") has no producer in the design. The D7 writer and activity log exist only on the presence path (`presence.py:6744`, activity log after `:6800`).
   - Fix in plan: route the hook through one presence-owned dispatch helper that applies both gates and writes the D7 row plus the activity-log row. Or drop the DB criterion.

6. **MEDIUM: idempotence and double-dispatch rules are incomplete.**
   - `transition()` clears an override silently (`house_state.py:200-202`). The hook must NOT fire there, because presence already dispatches with old = effective state.
   - `clear_override()` where the inferred state equals the override value leaves the effective state unchanged, so it must not dispatch. The plan covers only the "no override active" case.
   - `set_override(X)` where the effective state is already X must still pin the override, but without dispatching.
   - "Echo inference confidence" on clear: the machine has no access to it. Name the source.
   - Fix: state the rule as "dispatch iff the effective state changed" and test each of the three cases.

7. **MEDIUM: persisting the override is a behaviour change that is not declared.** Today a restart drops any override. With D1, a sleep or vacation override survives for up to 1800 s. Consumers that seed nothing (security, per-room chains at `coordinator.py:1590`) never see the restored override.
   - Fix: declare it explicitly as intended or not, and cover it in the non-goals and acceptance criteria.

8. **MEDIUM: the D0 section is internally inconsistent.**
   - Q1 is keyed on `sensor.uptime`, but the results used `homeassistant_start` events.
   - The exit criterion requires a staleness prior, but the results say "NOT measured".
   - Q2 is unspecified ("exact SQL keyed ... at run time"), which fails Review C's "D0 SQL reproducible" requirement.
   - Fix: replace the queries with the script actually run and record the down-time distribution (graceful vs watchdog).

9. **MEDIUM: the live criterion conflicts with operator policy.** "Deploy-and-restart at night" violates `feedback_no_restart_during_sleep`.
   - Fix: validate in the daytime with a `sleep` override, which exercises restored-override plus D1. Or get explicit operator consent for a night restart.

10. **LOW: knob ladder.** `HOUSE_STATE_RESTORE_MAX_STALE_S` at rung 1 with kill-switch 0 is fine. Needed: the heartbeat interval (if F2 is adopted) needs its own rung; the Store key and version need a const name.
    - Framings A/B/C are reasonably disjoint. B overlaps A on the override-restore decision; keep that decision in A.

11. **Build prediction: likely builder errors.**
    - (a) Calling `async_load` after the presence coordinator is registered or started. The plan says "before presence starts" but names no `manager.py` line; pin it.
    - (b) Firing the hook from `transition()` / `force_state()` (double dispatch). The spec must say "set/clear only".
    - (c) A test with a fake dict Store instead of real `Store` I/O.
    - (d) Keeping the original `state_since` (F3).
    - (e) A synchronous hook calling `async_dispatcher_send` from a non-loop thread via the service path. That path is fine today, but assert it is on the loop.
    - (f) Ignoring the fallback override paths in `select.py` / `__init__.py`.

## Checklist
- Prior art: REUSE of the Store pattern is correct; there is no existing house-state persistence (`HouseStateMachine.__init__` at `house_state.py:117`). PASS.
- Consumer census: LEAK (F1).
- Invariant falsifiable: yes, but the design cannot satisfy it (F2, F3, F4).
- Override single-hook: PASS on routing, LEAK on gates and DB (F5, F6).
- Acceptance criteria discriminating: no. The incident criterion does not separate house-state restore from zone-sleep restore (F4).

---

# REV 2 re-review (2026-09-29)

**Verdict: READY with the four plan edits below (R2-1..R2-4). None requires redesign.**

## F1-F11 disposition (verified by grep)
- F1 PASS: direct-reader table added (plan lines 87-90 and the rest). F2 PASS (heartbeat). F3 PASS: `state_since = now` plus a no-`transition()`-during-settle rule. The only `transition()` call site is `presence.py:6626`, and `force_state` has no callers, so the rule is enforceable at one site.
- F4 PASS: the trace (03:07:41 `arriving->home_night` in the same second as the zone_1/zone_2 writes, then 03:09:42 `->sleep` reverting them) establishes the house-state signal as the driver. The zone-sleep non-goal is justified.
- F5/F6 PASS: single helper, and the `suppress_hook` kwarg covers the `transition()`→override-clear path (`house_state.py:200-202`). Confidence is sourced via the adapter.
- F7 PASS: declared, with an operator flag. F8/F9/F10 PASS.
- F11 PASS: the load point before the loop at `manager.py:417` is correct (`async_start`, `manager.py:408-421`; no coordinator `async_setup` has run yet). The boot-settle flag name `_boot_settle_done` is correct (`presence.py:2232`, `:2315`).

## New findings
**R2-1 (HIGH): the deferred proposal has no discharge.** The rule "don't `transition()` during settle; re-compute when boot-settle lifts" needs something that re-computes. `_release_boot_settle` (`presence.py:2222-2240`) only releases the substrate gate. It does not re-run inference.
- The existing deferred-retry path (`presence.py:6852-6854`, `_schedule_deferred_retry` at `:4792`) only arms after a hysteresis rejection, which never happens when `transition()` is skipped.
- Result: a real divergence (e.g. restored `home_evening`, everyone actually left) waits for the next organic input event. Violates memory `feedback_suppression_needs_discharge`.
- Fix in plan: `_release_boot_settle` schedules `hass.async_create_task(self._run_inference("boot_settle_release"))`. Any release reason should do this: `real_input` at `:5459`, `ha_started` at `:2280`, `timeout` at `:2288`. Test it with a mutation drill on that call.

**R2-2 (MEDIUM): the stale/missing-restore path is a regression in what consumers read during settle.** On that path the machine sits at AWAY for the whole settle window (D0: ~5-9 min to `homeassistant_start`). Today the first inference walks it off AWAY before HVAC seeds; HVAC waits on `_ready_event`, which is set after the initial inference (`presence.py:2809`, `hvac.py:1410-1425`).
- Under REV 2, HVAC seeds `away`. Readers polling `manager.house_state` also read `away` until release: `binary_sensor.py:2204` (away), `energy.py:7378`, `notification_manager.py:3766`, `presence.py:1850`.
- HVAC then runs `update_room_conditions(house_state="away")` at setup (`hvac.py:1432-1434`).
- The restored path is fine: the restored value is what these readers see.
- Fix in plan: state the stale-path behaviour and verify it with a named test. Whether HVAC boot actuation on an `away` seed is held (v5.103.24 boot hold / arrester) must be cited with file:line, not assumed. If it is not held, allow the settle-time `transition()` ONLY when there is no restore (i.e. keep today's behaviour on the stale path).

**R2-3 (LOW): the observable signal on the no-restore path changes.** The first dispatch after release will be `away->arriving`, `->home_*` with trigger `boot_restore_diverged`, even when nothing was restored. Use a distinct trigger (`boot_settle_release`) for the no-restore case so the D7 and activity-log rows discriminate the two paths.

**R2-4 (LOW): heartbeat cadence. Recommend 300 s, not 60 s.**
- Cost: `Store.async_save` rewrites the whole JSON file (write-temp + rename). At 60 s that is 1,440 file rewrites a day on HAOS storage, for a ~200 B record. The heartbeat only needs to bound staleness error: saved_at lags actual shutdown by at most the interval. HA core's own `restore_state` persists every 15 min, which is precedent.
- Margin at 300 s: worst case = 300 s heartbeat lag + ~600 s observed down time = 900 s, still under the 1800 s bound with 900 s headroom. At 60 s the headroom is 1140 s; the extra 240 s buys nothing at 5-10 min down times.
- Add a stated constraint `HEARTBEAT_S <= STALE_MAX_S / 3` in the constant docstring so the two constants can't be tuned apart.
- Saving on every change plus HA stop plus a 300 s heartbeat is sane. Use `async_delay_save` for the change saves to coalesce bursts: override set plus zone propagation can fire several changes in one tick.

## Checklist
F1-F11 PASS. New: R2-1 LEAK (discharge), R2-2 needs evidence, R2-3/R2-4 cosmetic/tuning. Build may proceed once R2-1 and R2-2 are written into the plan.
