# SC garage lockout Phase 1: Review B (async, lifecycle, race, cross-coordinator)

- Branch: `feature/sc-garage-lockout-phase1` @ `a45a9b86`. Merge-base with local `develop` = `3153a918` (verified).
- Plan: `docs/planning/PLANNING_sc_garage_remote_lockout.md` rev 5 + Q-G1. Review A fixes (`7a923b7f`, `2a368d2a`) were in scope as code. A's framing is not repeated here.
- Mandatory reading done in full: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 853 lines) and `docs/architecture/SENSOR_FLEET_CLASSES.md`. Nothing in this review contradicts their corrections ledgers. The branch's §1 and §7 edits match the code.
- HA version pinned in `.venv-ha`: 2026.2.3.

## Verdict: FIX-REQUIRED (1 CRITICAL, 2 MEDIUM, 4 LOW)

## B-C1 CRITICAL: every timer and state-tracker callback runs in an executor thread

**Bug class:** HA thread-safety / job-type (no `@callback`), hidden by fake injected helpers in the test harness (#62 hollow anchor variant).

`security_lock_regime.py` has no `@callback` decorator anywhere (`grep -n callback` finds only `add_done_callback` at :1144). HA's `HassJob` types any plain function or bound method that is neither a coroutine nor `@callback` as **Executor** (`homeassistant/core.py:347-360` `get_hassjob_callable_job_type`). `async_call_later` (`helpers/event.py:1599-1617` → `_run_async_call_action` → `async_run_hass_job`) and `async_track_state_change_event` / `async_track_state_added_domain` (`helpers/event.py:481`, `job_type=None`) therefore run these callbacks on a worker thread:

`_on_person_event`, `_on_person_added`, `_on_person_removed`, `_on_distance_event`, `_on_lockout_event`, `_on_backstop`, `_on_reengage_timer`, `_on_boot_recheck`, `_on_guest_clock`, and the read-back lambda at :908.

I checked this directly: `HassJob(getattr(regime, name)).job_type` gives `HassJobType.Executor` for all ten.

**Real-HA probe (pytest-homeassistant `hass` fixture, scratch file, since deleted):** I scheduled a callback with `async_call_later(hass, 0, ...)` and called `regime._spawn(...)` from inside it. The callback ran on a different thread ID from the loop, and `_spawn` raised:

> RuntimeError("Detected that custom integration 'universal_room_automation' calls hass.async_create_task from a thread other than the event loop …", at security_lock_regime.py line 1141)

(`helpers/frame.py:415-426`: `custom_integration_behavior=ReportBehavior.ERROR`.)

**Consequences, all on legal default config.** Only the house-state edge, the P2 signal and the hazard path run on the loop, because SC's dispatcher handlers are `@callback` (`security.py:1128`, `:2118`, `:2205`), and the kill switch runs from `async_turn_off`. Everything else is broken:

1. **P1 arrival (the core feature).** SLEEP has engaged the lockouts at 23:30. A resident drives home at 01:00 and `person.x` goes `not_home → home`. `_on_person_event` runs in the executor and `_release` adds the entity to `_release_inflight` (:845). `_spawn` (:848) then raises, so no `lock.unlock` is ever issued. The car remote does not open the garage.
2. **The `_release_inflight` poison makes it worse.** The entity is never discarded from the set. Every later `_release` skips it (:843 "H3b"), including the morning WAKING edge. `engage_predicate` returns `release_inflight` for it forever (:976). Net effect: the lockout stays **locked all day, with no NM**, until a reload. That is the unsafe direction.
3. **P5 proximity and the approach zone** fail the same way (:812, :726).
4. **Morning backstop (INV-4).** Repro: the house stays in SLEEP past sleep_end + 60 min (the case the sleep-mask `sleep_raw_hold` trip-wire exists for). `_on_backstop` fires in the executor, `_release("backstop")` raises, and the entity is poisoned as in item 2.
5. **Read-back retry and the HIGH NM.** `_on_readback` runs in the executor. If the entity still reads `locked`, `_spawn` raises at :920 or :923. The retry never runs, no NM is sent, and the entity stays in `_release_inflight` forever. This removes the read-back + retry + HIGH NM chain from rev 5 §6.1b.
6. **Re-engage (INV-3) and the Q-G1 guest clock never engage.** `_request_engage` raises at :1102 and :634. `_on_guest_clock` also re-arms `async_call_later` from the worker thread (:623), and `loop.call_at` is not thread-safe.
7. **Off-loop mutation.** `_on_person_added` / `_removed` call `async_track_state_change_event` and `Store.async_delay_save` off the loop. Every callback also mutates `release_gen`, `releasing_set` and `_engage_inflight` off the loop. Those are data races with the loop-side engage task, and they break the INV-2 "no yield between check and call" reasoning, because a worker thread can bump `release_gen` at any bytecode boundary of `_async_engage`.

**Why the suite is green:** `_lockout_harness.py:132-177` fakes `call_later`, `track_state` and the domain trackers, and calls the callback synchronously on the loop. `test_sc_garage_lockout.py:1368` monkeypatches the real tracker away. No test runs a regime callback through a real `HassJob`.

**Must-fix:**
- Decorate all nine methods with `homeassistant.core.callback`.
- Replace the :908 lambda with a `@callback` method bound through `functools.partial`. `get_hassjob_callable_job_type` unwraps partials before `is_callback`. The `now` argument arrives last.
- Add a test that asserts `HassJob(cb).job_type is HassJobType.Callback` for every callable the regime passes to `_call_later` / `_track_*`. The cheapest way is to wrap the harness fakes so they assert this on registration.
- Defensive: in `_release`, if `_spawn` raises, discard `ent` from `_release_inflight` so one failure cannot poison the entity forever.

## B-M1 MEDIUM: teardown cancels an in-flight release unlock, and the new instance never retries it

**Bug class:** cancellation across reload / lost discharge.

`async_teardown` cancels every task in `_tasks` (:521-523), including `_async_unlock`, which awaits `lock.unlock` with `blocking=True`. In HA 2026.2, `ServiceRegistry.async_call` awaits the handler coroutine directly when blocking (core.py, `response_data = await coro`), so the cancellation propagates into the entity's `async_unlock`.

Repro: lockouts engaged at night. A resident arrives (P1 or P5, after C1 is fixed), and an SC or CM reload happens within the unlock round-trip (a non-suppressed options save, or the SC Enabled switch toggled off and on). The unlock is cancelled. The new instance's `_boot_rebuild` sees `locked` and rebuilds `reason` but never releases (H1). The person is already `home`, so no new edge arrives. The lockout stays locked until WAKING or the backstop.

**Fix:** in teardown, do not cancel the `_async_unlock` tasks. Await them with a bounded timeout, like `async_release_if_disabled` does (5 s). Alternatively, carry a "release pending" mark in the Store and honour it in `_boot_rebuild`.

## B-M2 MEDIUM: an exception after `_release_inflight.add` leaves the entity stuck (independent of C1)

**Bug class:** state set before a fallible step, with no discharge (suppression needs a discharge).

The order at `_release` :845-848 is: add to `_release_inflight`, then `_engage_inflight.pop`, then `_spawn`. Any raise from `_spawn`, for example `hass.async_create_task` during HA `final_write` or after loop close, leaves the entity blocked from release and from engage for the life of the instance. The same applies at `_on_readback` :920.

**Fix:** use try/except around `_spawn` and discard on failure (the same defensive fix as C1).

## LOW

- **B-L1: NM dedup masks the second lockout.** `_notify_failure` uses one title and `location="garage"` for both lockouts. NM dedups on `coordinator:title:location` for 300 s at HIGH (`notification_manager.py:4114-4131`, `NM_DEDUP_HIGH=300`). If both openers fail together, only the first entity is named. The flood itself is bounded to 1 per 5 min (cleared). Fix: put the entity in `location`, or in the title.
- **B-L2: teardown time is unbounded in count.** `async_release_if_disabled` runs serially for each entity: unlock up to 5 s, then the NM up to 5 s. With 2 lockouts that can add up to 20 s to an SC disable reload. Acceptable, but say so in the README.
- **B-L3: Store schema is not validated.** `data.get("residents", [])` (:393) on a hand-corrupted file holding a string iterates characters into bogus `person` subscriptions. Fix: `isinstance(list)` guard. Concurrent saves are cleared: there is one `async_delay_save` per instance and the old instance's pending save fires before the new one's. Load failure is handled (:394-399).
- **B-L4: boot-window HOME_* or WAKING edges release (informational).** `on_house_state_changed` gates only engage on `_in_boot_window` (:610). A transient HOME_NIGHT replay in the first 120 s after a night restart releases the lockouts until the next SLEEP edge after the window. This is the fail-safe direction and consistent with plan INV-5. Noted for the README.

## Cleared (with evidence)

- **INV-2 synchronous pre-lock check.** `engage_predicate` (:967-995) contains no `await`. In HA 2026.2, `ServiceRegistry.async_call(blocking=False)` has no `await` before `async_create_task_internal(...)`; return at the `if not blocking:` branch (the only `await` is the blocking `await coro`). The INV-2 comment at :1009 therefore holds once C1 removes the off-loop writers. Residual: lock and unlock device ordering is the integration's FIFO task order, not URA's.
- **Teardown coverage.** Every handle is cancelled in `async_teardown` (:502-524): person, added and removed trackers, the lockout tracker, distance, backstop, boot recheck, guest clock, re-engage, read-backs and tasks. I found no handle left over after repeated reloads, and `_subscribe_person` dedups.
- **Restart ordering.** `manager.async_start` restores house state before any coordinator `async_setup` (`manager.py:470-499`), so `_boot_rebuild` reads the restored state. Boot edges only rebuild `reason` (`:610-613`). HA stop does not run SC teardown (`manager.py:54` comment), so no release fires at shutdown. `async_release_if_disabled` reads the live CM entry, and on a restart or ordinary reload `coordinator_should_run` is True, so it releases nothing (:542).
- **Observation mode.** Engage logs `would_engage` (:1000). Release ignores observation mode (by design). The hazard and P2 feeds sit above the observation returns (`security.py` :2127, :2212).
- **Optimizer layer 1.** The block is cover-only, synchronous, and fails closed. It returns before service dispatch and touches no other optimizer action.
- **Hourly sweep.** It iterates `_lock_entities` and `_garage_entities` only (`security.py` ~1755). Lockouts are kept out of the lock list by the options validator (`config_flow.py:9055-9065`). The sweep shares no write path with engage.
- **Lock entity unavailable mid-command.** `_release` skips unreal states with a once-per-entity warning (:832-838). `engage_predicate` requires `unlocked`. The read-back treats non-`locked` as done (:916). After C1, an entity that goes unavailable during a release clears `_release_inflight` at read-back.
- **Kill switch.** OFF calls `_release(force=True)` from the loop after the option is persisted (`switch.py`). The keys are in `OPTIONS_RELOAD_SUPPRESS_KEYS`, so no reload happens. OFF to ON never catches up.

## Summary

| Severity | Found | Must-fix |
|---|---|---|
| CRITICAL | 1 (B-C1) | yes |
| HIGH | 0 | – |
| MEDIUM | 2 (B-M1, B-M2) | yes |
| LOW | 4 | B-L1 and B-L3 recommended |

| Bug class | Count |
|---|---|
| HA thread-safety / missing `@callback` (new: "executor-typed callback") | 1 |
| Fake-helper harness hides the real job type (#62 variant) | 1 (within C1) |
| Lost discharge / state set before a fallible step | 2 |
| Dedup collision | 1 |

**QUALITY_CONTEXT recommendation:** add the class "Executor-typed HA callback": a plain method passed to `async_call_later` / `async_track_*` without `@callback` runs in a worker thread. Its anchor test is `HassJob(cb).job_type is HassJobType.Callback`, asserted inside any injected fake helper.
