# Plan review 2 of 2: SC garage remote lockout (rev 3), adversarial build-prediction

**Plan:** `docs/planning/PLANNING_sc_garage_remote_lockout.md` rev 3. **Card:** GARAGE-REMOTE-LOCKOUT-SCHEDULE-1. **Date:** 2026-11-07.
**Framing:** what will the builder get wrong reading this plan? Review 1 (completeness) is not repeated here.
**Reads done:** `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all of it, including the §10 ledger through #29) and `SENSOR_FLEET_CLASSES.md` (all of it). No ledger claim is re-asserted. Code read on develop: `security.py` (evaluate 801-833, house-state bridge 1086-1130, lockdown and sweep 1640-1725, optimizer 1830-1912, hazard and arrival 2051-2125, teardown 841-866), `base.py:189-197, 287-299`, `manager.py:925-975, 1249-1285`, `cover_ownership.py` (whole file), `optimization.py:505-545, 4895-4995`, `switch.py:665-762`, `presence.py:2575-2600, 8484-8530`. Live HA state read for both covers, both lockouts and three proximity sensors.

**Verdict: FIX-PLAN.** One CRITICAL and three HIGH findings. Each is a defect the builder would ship faithfully from the plan text. All of them are plan edits; none needs new research.

---

## Findings

### CRITICAL

**C1. The SC-disable release (H2a) hooks a code path that production never calls.** `manager.async_set_coordinator_enabled` (`manager.py:1249-1283`) has **no caller** anywhere in `custom_components/` or `quality/` (grep: only its `def`). The only way an operator disables SC is `switch.ura_security_coordinator_enabled`, a `CoordinatorEnabledSwitch` (`switch.py:259-268`). Its `async_turn_off` (`switch.py:753-761`) writes `security_coordinator_enabled: False` to options and **reloads the integration entry**. The result is `async_teardown` (`security.py:841`), and on re-setup SC is not constructed. The plan says teardown "does not release" (§1.2, §6.1, D4 `test_sc_teardown_does_not_release`). So the real disable path strands a locked lockout with no URA release ever, which is the "family locked out" case H2a was meant to close. A `test_sc_disable_edge_releases` that sets `coordinator.enabled = False` passes on dead code (Bug Class #62, hollow anchor; #53, computed but not consumed).
*Fix in plan:* put the release on the real edge. Either `CoordinatorEnabledSwitch.async_turn_off` for `coordinator_id == "security"` awaits a regime release (direct, with read-back) **before** `async_update_entry` and reload, or teardown releases when the CM option now reads `security_coordinator_enabled is False`. The second option tells disable-reload apart from restart and from an ordinary reload. Keep the setter override only if it costs nothing; it must not be what the tests anchor on. Test: drive `switch.async_turn_off` with a fake reload and assert `lock.unlock` was called before the reload.

### HIGH

**H1. A queued engage can land after a release (stale-intent race).** Engage goes through `manager.queue_intent` → 100 ms batch → `evaluate()` (`manager.py:927-958`). Release is direct and immediate. Legal repro: house → SLEEP at 23:00:00.000 queues an engage. A resident `person` → `home` edge at 23:00:00.050 releases directly; both lockouts still read `unlocked`, so nothing is written. At 23:00:00.100 the batch runs, `evaluate()` emits `lock.lock`, and the lockout locks on top of an arrival (INV-2 / INV-3 broken). The same shape applies to the kill switch going ON→OFF while an engage is queued, and to the re-engage timer firing just after an arrival. The plan describes the path split but never says that `evaluate()` must re-validate.
*Fix in plan:* the `lock_regime` branch in `evaluate()` re-checks at evaluate time: kill switch ON, SC enabled, current house state still SLEEP/VACATION, and no arrival release since the intent's `queued_at`. The intent carries a monotonically increasing regime generation, and any release bumps it; a stale generation means no action. Test: `test_engage_intent_dropped_if_release_after_queue`.

**H2. INV-1 depends on SC being alive, and the ownership check fails open.** (a) The optimizer veto is advisory. `optimization.py:4949` dispatches unless some sibling has pushed a veto (`await_veto`, `:505-536`). If SC is disabled (C1 path: not constructed) or torn down mid-reload, nobody vetoes and an L2 `cover.open_cover` on a garage goes through. Phase 1 is still fail-closed in the common case, but INV-1 is stated integration-wide and Phase 2's safety case leans on it. (b) `cover_ownership.is_security_owned_cover` swallows every exception and returns **False**, i.e. not owned (`cover_ownership.py:96-139`, docstring "fail open"). §6.3's "any exception in the check → veto" therefore cannot happen, and `test_optimizer_cover_ownership_error_vetoes` can only pass by monkeypatching the helper to raise, which tests a branch production never takes (#62).
*Fix in plan:* (1) add a hard filter in the optimizer's own dispatch, the same shape as the `egress_paused` disallow at `optimization.py:~4890`. Any `cover.*` target for which `is_security_owned_cover` is True is DISALLOWED there, whether or not SC is present. Keep the SC veto as the second layer. (2) In both layers, also treat any entity in `CONF_SECURITY_GARAGE_ENTITIES` (CM config) as owned, so a device_class change cannot open the hole. (3) Replace the error test with one in which the state is missing and the registry is unavailable, and the garage is in `security_garage_entities`; expected result: vetoed.

**H3. Arrival flaps release repeatedly, and one arrival produces up to four unlock calls.** P1 counts `unknown`/`unavailable` → `home` as an arrival (§4.1). A resident asleep at home whose `person` entity blips through `unknown`/`unavailable` (companion-app reconnect, person/tracker integration reload, ledger #27-style tracker churn) therefore releases at 03:00 and schedules a re-engage 15 min later, every time it blips. For a genuine arrival, P1 + P2 + P5 + house ARRIVING all fire within seconds. Release uses `blocking=False` (the hazard pattern), so each trigger still reads `locked`: the opener gets up to 4 `lock.unlock` calls, 4 read-back tasks and 4 re-engage timers unless the builder invents supersession. The plan doesn't specify it.
*Fix in plan:* (a) An arrival from `unknown`/`unavailable` counts only if the person's last *real* state, held before the blip, was not `home`. This REUSES the `_min_away_minutes` (15) idea already used for `AUTO_OPEN_MIN_AWAY_MIN`. (b) A per-entity in-flight latch: no second unlock while a read-back is pending. (c) One re-engage handle, superseded on each arrival (cancel, then reschedule). (d) All regime timers (backstop, boot recheck, re-engage, read-back) are cancelled in `async_teardown`; the current teardown (`security.py:841-866`) cancels only the house-state debounce. Tests: `test_unknown_blip_while_home_no_release`, `test_multi_trigger_arrival_single_unlock`, `test_reengage_superseded_by_second_arrival`, `test_teardown_cancels_regime_timers`.

### MEDIUM

**M1. Boot really does produce engage edges, and the plan doesn't say how to treat them.** `_release_boot_settle` emits one `SIGNAL_HOUSE_STATE_CHANGED` with `trigger="override_set"`, `source="boot_settle_override"` whenever a restored override differs from the inferred state (`presence.py:2575-2597`). VACATION is an override that survives restart. Legal repro: VACATION, the house-sitter has the operator unlock the lockout from the app at 14:00, HA restarts at 15:00, boot settle dispatches inferred → VACATION, the regime treats it as a VACATION edge and engages. That contradicts "Boot never engages" (§5.2). The same thing happens when the restore is stale (>1800 s, `house_state.py`) and the first inference after settle yields SLEEP at 02:00: that is an ordinary SLEEP edge, and it re-locks a lockout the operator had manually released (INV `test_manual_unlock_not_reasserted`).
*Fix in plan:* edges whose `source == "boot_settle_override"`, and any edge within `GARAGE_LOCKOUT_BOOT_RECHECK_S` of setup, only rebuild `reason`; they never engage. Test: `test_boot_settle_override_vacation_does_not_engage`.

**M2. Re-engage can land on a resident who is still on the way in (P5 makes this worse).** P5 releases at 1.5 km. Re-engage fires `REENGAGE_DELAY_S` (900 s) later if "both doors closed, house SLEEP, before sleep_end_hour". Legal repro: Ezinne crosses 1500 m at 02:00, stops for fuel or drops someone off, and is still at 800 m at 02:15. The re-engage locks, and her remote then works only if the P1 `home` edge fires before she presses it. INV-3 says no re-engage on top of a resident, but the condition doesn't include "the releasing resident has reached home or turned back".
*Fix in plan:* re-engage additionally requires every resident whose arrival caused the release to read `home`, or to read beyond the radius again. Test: `test_reengage_waits_for_proximity_released_resident`.

**M3. Hazard release placement invites a non-byte-identical move.** "Placed before the `:2059` observation return" (§3.2, §6.1). A builder can satisfy that by hoisting the whole hazard block above `if self.observation_mode`, which would then also unlock the egress door locks under observation. That changes existing behaviour. *Fix:* say explicitly that only the new lockout-release call goes above `:2059`. It stays below `:2057` `not self._enabled`, because the disabled case is C1's job. The existing door-egress loop stays after the observation return, unchanged. Test: `test_hazard_under_observation_releases_lockouts_not_door_locks`.

**M4. Proximity unit and edge semantics are under-specified.** Live: `sensor.madronehaos_oji_udezue_distance` = `20833.33` with `unit_of_measurement: ft`; Jaya and Ziri read `unknown`; `direction_of_travel` reads `unknown` (options `arrived/away_from/stationary/towards`). A builder will hand-roll `* 0.3048`. The display unit is user-changeable, so the plan should REUSE HA's `homeassistant.util.unit_conversion.DistanceConverter` (verify the import in the build). Also unstated: whether `unknown` → ≤ R (a phone coming online inside the radius, or the first sample after a restart) is a crossing. Recommend not, with the reason that P1 covers it. And the plan doesn't say whether proximity measures to the zone centre or the zone edge, or reads 0 inside the zone. That is UNVERIFIED here (not read in HA source), and D0's haversine-to-centre recompute can disagree by up to the 150 m radius. *Fix:* name the converter; state the crossing rule (previous value numeric > R, current numeric ≤ R); add to D0 a note to read HA proximity's distance definition. Discriminating test values: R = 1500 m with a reading of **3000 ft** (914 m) must release. A no-conversion build compares 3000 > 1500 and does not release, so the test fails as it should. 6000 ft does not discriminate, because both builds skip it.

**M5. Phase 2 INV-1A: a restart or reload in the middle of an episode can produce a second open.** INV-1A in my words: *every `cover.open_cover` from `_fire_open()` is sent only when every listed gate holds at the instant of the call, and at most once per real arrival.* Legal-config repro that breaks the second half: auto-open ON, shadow OFF, the operator approaches at 25 km/h, and the open fires at T. An integration reload (routine; reload storms are on record) or a restart happens at T+60 s. The operator closes the door at T+90 s while still in the driveway. The fresh controller has no memory of the episode ("restart: rev 2 text stands", and §6.2 doesn't show it persisted), sees fresh fast fixes with the operator not yet `home`, the door `closed` and no alert, starts a new episode and opens again. *Fix:* persist `last_open_at[D]` (Store or a decision-log read-back at setup) and add a boot blackout of `AUTO_OPEN_EPISODE_MAX_S` after setup. Test: `test_no_second_open_across_reload_mid_episode`.

**M6. Phase 2: name the stolen-phone-plus-car residual.** With the gates as written, whoever holds the operator's phone in a moving car opens the garage. INV-1A has no corroborator gate (CX-90 telematics, A4, is "corroborator at best"). That may be acceptable for a trial, but it belongs in §5.2's named residuals and in the README, and D's Phase 2 repro list should include it.

### LOW

- **L1. Kill switch OFF → ON while the house already reads SLEEP:** edge-only (INV-5) implies no engage until the next SLEEP edge. State this; a builder will likely "catch up" and engage. Test `test_kill_switch_on_mid_sleep_no_engage`.
- **L2. Presence observation suppresses `SIGNAL_HOUSE_STATE_CHANGED`** (`presence.py:8518-8524`), so under Presence observation there are no SLEEP/WAKING edges. The regime then never engages, and a lockout engaged before observation was switched on releases only by backstop or arrival. The direction is fail-safe, but it should be listed alongside the SC-observation residual.
- **L3. `CONF_SECURITY_AUTO_OPEN_SHADOW` "absent = ON" vs the options-backed switch pattern:** `_IntegrationOptionsSwitch` reads a default; make sure its default for this key is True and that the test reads the switch entity, not the constant.
- **L4. Rung check:** `GARAGE_LOCKOUT_RELEASE_MAX_S` is a test oracle, not a behavioural number. Fine at rung 1, but mark it "not read by production code" so no builder wires a timeout to it.

---

## Q12 and H3 cover check (answered live)

`cover.konnected_f0f5bd523b00_garage_door` and `cover.ratgdov25i_dbfe2a_door` both carry `device_class: garage` in **state attributes** (HA read, 2026-11-07), so `is_security_owned_cover` returns True on its first branch (`cover_ownership.py:117-118`). D0 Q12 is answered and P2-A's device-class half passes. The residual risk is a future `device_class` change or a state-less window. In that window the helper falls back to the registry, and if that also fails it returns False (fail open), which is why H2 asks for the `CONF_SECURITY_GARAGE_ENTITIES` membership leg. Both lockouts read `unlocked` right now.

## Hollow or non-discriminating named tests

| Test (plan) | Problem | Make it discriminate |
|---|---|---|
| `test_sc_disable_edge_releases` | Exercises a setter with no production caller (C1) | Drive `CoordinatorEnabledSwitch.async_turn_off` |
| `test_optimizer_cover_ownership_error_vetoes` | Helper never raises (H2b) | State missing, registry unavailable, entity in garage config → vetoed |
| `test_regime_never_emits_cover_service`, `test_only_auto_open_module_emits_cover_open` | Likely to be written as source greps (#62) | Drive every regime / SC / optimizer path with a recording `hass.services.async_call`, assert no `cover.open_cover` / `toggle` / `set_cover_position` |
| `test_arming_path_unchanged_byte_identical` | "Byte-identical" has no oracle as written | Snapshot the action list and ArmedState for an auto-follow-ON SLEEP edge, before and after |
| `test_proximity_crossing_releases` | Passes with or without unit conversion if values are poorly chosen | 3000 ft with R = 1500 m must release (M4) |
| `test_release_under_sc_observation` | Passes if it asserts on an intent or log line | Assert the recorded `lock.unlock` service call |
| Missing | — | `test_engage_intent_dropped_if_release_after_queue` (H1), `test_unknown_blip_while_home_no_release`, `test_multi_trigger_arrival_single_unlock`, `test_teardown_cancels_regime_timers` (H3), `test_boot_settle_override_vacation_does_not_engage` (M1) |

## Predicted builder mistakes (if the plan ships as is)

1. Overrides the `enabled` setter, tests it, ships. The real switch path still strands the lockout (C1).
2. Engage branch in `evaluate()` trusts the queued intent; locks after a direct release (H1).
3. Hoists the whole hazard block above the observation return (M3).
4. Treats every `unknown→home` as an arrival; no in-flight latch; multiple re-engage timers (H3).
5. Hand-rolls ft → m; treats the first numeric sample after `unknown` as a crossing (M4).
6. Wraps `is_security_owned_cover` in `try/except → veto` and believes it fails closed (H2b).
7. Lets `boot_settle_override` VACATION engage at boot (M1).
8. Forgets to cancel backstop, recheck and re-engage handles in `async_teardown` (H3d). The existing teardown cancels only the auto-follow debounce.
9. Phase 2: keeps episode state in memory only (M5).

## Sequencing (SECURITY-LOCK-SWEEP-RETRY-CAP-1 / SC-SWEEP-CLOSES-OPEN-GARAGE-1)

The plan's order holds (retry-cap first, then re-cite). Two additions. (a) Phase 1 adds code near `security.py:2051-2125` and to `honor_optimizer_intent`, which is outside `_evaluate_lock_check`. Expect line drift only, but **C1's fix touches `switch.py` `CoordinatorEnabledSwitch`**, so add it to the re-cite list. (b) SC-SWEEP-CLOSES-OPEN-GARAGE-1 will edit the sweep's garage block (`security.py:~1705-1723`), the same function the retry-cap branch changes. It must be cut from develop **after** retry-cap merges, never in parallel, and its hold-off read of `auto_opened_at[D]` needs the Phase 2 controller to exist. So build P2-B's hold-off as a generic `garage_close_holdoff_until[D]` API on SC that Phase 2 later stamps. Otherwise P2-B can't be tested before D6 exists, and it becomes circular.

## Invariant checklist

| Invariant | Status in plan rev 3 |
|---|---|
| INV-1 (one garage-raising writer) | LEAK when SC is absent (H2a); fail-open helper (H2b) |
| INV-1A (auto-open gated, once per episode) | LEAK on reload or restart mid-episode (M5) |
| INV-1B | holds as written (depends on P2-B) |
| INV-2 (family release) | LEAK on the real SC-disable path (C1); engage race (H1) |
| INV-3 (no re-engage on a resident) | LEAK via P5 + re-engage (M2); stale engage (H1) |
| INV-4 (morning, across restart) | holds if the boot recheck is built; M1 adds a boot engage path |
| INV-5 (edge-only) | ambiguous for the kill-switch ON edge and boot edges (L1, M1) |
| INV-6 (AWAY/GUEST inert) | holds |

## Review path

Fix C1, H1-H3 and M1-M5 in the plan as rev 4. Re-review is a single delta pass, since these are local edits, not a re-scope. Then build Phase 1 under the Tier 2-DB protocol: A/B/C framings, with C mutating the C1 switch-edge release, the H1 evaluate-time recheck and the H2 optimizer-side filter as named sites. Phase 2 keeps its two Tier-3 plan reviews before D6. M5 and M6 must be in the Phase 2 plan by then.
