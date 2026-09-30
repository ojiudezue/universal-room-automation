# v5.103.27 — House-state restart restore + override dispatch (DRAFT, HELD)

**Status:** DRAFT — deploy HELD until operator go.
**Plan:** `docs/planning/PLANNING_house_state_restart_and_override.md` (REV 2.1).
**Plan review:** `docs/reviews/code-review/plan_review_house_state_restart_and_override.md`
(READY-after-four-edits, applied in REV 2.1).
**Tier:** 2-DB (operator-elevated — presence↔HVAC↔security↔every consumer ripple).
**Cards:** HOUSE-STATE-SLEEP-LOST-ON-RESTART-1, HOUSE-STATE-OVERRIDE-NOT-DISPATCHED-1.

## What ships

### D1 — House-state survives HA restart

- Last house-state persisted via `helpers.storage.Store` (key
  `universal_room_automation.house_state`, version `1`).
- Save triggers: (a) debounced on any accepted mutation
  (`Store.async_delay_save`, 1.0 s coalesce); (b) heartbeat every 300 s
  (`async_track_time_interval`) so `saved_at` reflects LIVENESS; (c) forced
  flush on `EVENT_HOMEASSISTANT_STOP`.
- Restore runs in `CoordinatorManager.async_start` BEFORE the coordinator
  setup loop — no consumer has yet read `manager.house_state`.
- Staleness bound `HOUSE_STATE_RESTORE_MAX_STALE_S = 1800` (30 min).
  Kill-switch: set to `0` to disable restore (machine always starts AWAY).
- On successful restore: `_state_since` re-armed to now (F3 — hysteresis
  honoured on first inference); `_boot_restore_active = True` (R2-2 marker).
- R2-1 reconciliation tick scheduled at the end of
  `presence._release_boot_settle` (the single idempotent convergence point).
  Distinct trigger labels (R2-3):
  - `boot_restore_confirmed` — restore succeeded and inference agrees (no
    dispatch; memory-writer boot-suppresses).
  - `boot_restore_diverged` — restore succeeded and inference differs (one
    dispatch, one D7 row, one activity-log row).
  - `boot_settle_release` — no restore was active (cold-boot walk; one
    dispatch with the new label).
- R2-2: presence defers `machine.transition()` during boot-settle ONLY when
  `_boot_restore_active` is True. Cold-boot behaviour is preserved.

### D2 — Manual override dispatches SIGNAL_HOUSE_STATE_CHANGED

- Single presence-owned dispatch helper `_dispatch_house_state_change`
  applies boot-settle + observation-mode gates, dispatches the canonical
  payload, writes the D7 memory row + activity-log row. Both inference
  and override paths route through it (byte-identical payload shape).
- `HouseStateMachine.on_state_change` hook wired by the manager to an
  adapter that resolves presence and calls the helper.
- F6 idempotence:
  - `set_override(X)` fires iff effective state changes; no-op when
    inferred already equals X.
  - `clear_override()` fires iff there was an override AND the inferred
    state differs from the cleared value.
  - `transition()` clears an override silently — hook suppressed via
    `suppress_hook=True` on the internal `clear_override` call, so
    presence's own dispatch carries the single (old_effective, new)
    payload (double-dispatch guard).

### Files touched

- `custom_components/universal_room_automation/domain_coordinators/house_state.py`
- `custom_components/universal_room_automation/domain_coordinators/manager.py`
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
- `custom_components/universal_room_automation/memory_writers.py`
- `quality/tests/test_house_state_restore_override.py` (new)
- `quality/tests/test_memory_writers.py` (parametrize update for R2-3 vocab)

## Operator decisions — RULED 2026-09-29

Both are single-line module-constant flips in `house_state.py`; operator
ruled **KEEP BOTH DEFAULTS**:

1. **`HOUSE_STATE_OVERRIDE_SURVIVES_RESTART = True`** — **YES**
   (operator ruling 2026-09-29). An operator who forces SLEEP just before
   a restart clearly intends it to persist; dropping it made
   "restart-as-remedy" more dangerous than it should be.
2. **`HOUSE_STATE_OVERRIDE_ENDS_ARRESTER_HOLDS = True`** — **YES**
   (operator ruling 2026-09-29). D2 dispatches on override set/clear are
   treated as first-class house-state transitions, so
   `hvac_override.py:903 sunset_immune_holds` firing on them is the
   intended behaviour and matches the semantic parity with inferred
   transitions.

Both constants remain in `house_state.py` as named module constants for
one-line flip-back should either ruling change.

## Acceptance criteria (prospective — populate at Live Validation)

### Unit / integration / drills (all in `test_house_state_restore_override.py`)

| # | Test | Purpose | Result |
|---|---|---|---|
| 1 | `test_heartbeat_less_than_third_of_stale_max` | Meta-invariant: `HEARTBEAT_S <= STALE_MAX_S/3` | PASS |
| 2 | `test_store_constants_have_expected_shape` | Store key/version pinned | PASS |
| 3 | `test_to_persisted_dict_shape` | Persisted payload contract | PASS |
| 4 | `test_apply_restored_fresh_reapplies_state_and_rearms_dwell` | F3 dwell re-arm on restore | PASS |
| 5 | `test_apply_restored_stale_falls_back_to_away_default` | Staleness bound honoured | PASS |
| 6 | `test_apply_restored_disabled_when_max_stale_zero` | Kill-switch (0 disables restore) | PASS |
| 7 | `test_apply_restored_corrupt_payload_falls_back` | Corrupt payload -> AWAY, no crash | PASS |
| 8 | `test_apply_restored_no_record` | Missing record -> AWAY | PASS |
| 9 | `test_override_survives_restart_can_be_disabled` | Operator-flip flag works | PASS |
| 10 | `test_persist_hook_fires_on_transition_and_override` | All 4 mutation paths save | PASS |
| 11-15 | `test_set_override_*` / `test_clear_override_*` / `test_transition_clears_override_but_hook_suppressed` | F6 idempotence + double-dispatch guard | PASS |
| 16 | `test_store_roundtrip_real_io` | REAL `helpers.storage.Store` I/O against tmp path (F11) | PASS |
| 17 | `test_r2_1_diverged_dispatches_boot_restore_diverged` | Real `PresenceCoordinator._release_boot_settle` -> R2-1 tick dispatches `trigger=boot_restore_diverged` | PASS |
| 18 | `test_r2_1_no_restore_uses_boot_settle_release_trigger` | Cold-boot path dispatches `trigger=boot_settle_release` | PASS |
| 19 | `test_r2_1_mutation_drill_scheduling_line_is_load_bearing` | Runtime-neutered `hass.async_create_task` -> tick never runs | PASS |
| 20 | `test_r2_2_deferral_predicate_gates_transition` | Real `_should_defer_transition_for_boot_restore` returns True during boot-settle-with-restore, False otherwise | PASS |
| 21 | `test_r2_2_guard_is_wired_at_the_transition_call_site` | AST anchor — guard referenced inside `_run_inference` | PASS |
| 22 | `test_r2_2_mutation_drill_removing_guard_breaks_predicate_test` | Guard replaced with `return False` -> True/False flips detectable | PASS |
| 23 | `test_d2_service_path_reaches_dispatch_helper_once` | REAL `CoordinatorManager._wire_house_state_persistence` -> `set_house_state_override("sleep")` -> exactly one `SIGNAL_HOUSE_STATE_CHANGED` with canonical `{old_state,new_state,trigger,confidence}` payload received | PASS |
| 24 | `test_d2_bypassing_dispatch_helper_hook_yields_no_signal` | Hook unwired -> zero signals (proves the hook is load-bearing) | PASS |
| 25 | `test_mutation_drill_deleting_persist_hook_call_breaks_persist_test` | `_fire_persist_change` neutered -> zero saves | PASS |

### Real-source mutation drills (operator wire-in anchor rule)

Every drill: edit production source in place -> `shutil.rmtree` all
`__pycache__` -> run the target test(s) -> restore via a `cp` from
`/tmp/*.bak` -> confirm marker count == 0 in the file + full 38/38 pass.

| Drill | Source edit | Expected red | Observed |
|---|---|---|---|
| R2-1 | Delete `self.hass.async_create_task(self._boot_settle_reconciliation_tick())` in `presence._release_boot_settle` | R2-1 diverged + no-restore tests fail | CONFIRMED — both FAIL, tick never runs; mutation drill test (independent) passes; restored clean. |
| R2-2 / C-HIGH-2 | Replace `_should_defer_transition_for_boot_restore` body with `return False` | R2-2 predicate test + drill test + `test_c_high_2_run_inference_defers_when_restore_active` fail | CONFIRMED — 3 FAIL; AST anchor still passes (guard reference intact); restored clean. |
| D2 | Replace `machine.on_state_change = _on_state_change` with `pass` in `manager._wire_house_state_persistence` | `test_d2_service_path_reaches_dispatch_helper_once` fails | CONFIRMED — 0 signals received; hook-bypass symmetric test still passes; restored clean. |
| A-HIGH-1 | Re-inject an inline `db.log_house_state_change(...)` block at the `_run_inference` site | `test_a_high_1_source_no_inline_dispatch_at_run_inference` fails | CONFIRMED — AST/source anchor FAILS on the reintroduced text; runtime double-write would surface via `test_a_high_1_dispatch_helper_is_only_writer`; restored clean. |
| A-MED-2 | Replace `if machine is not None and getattr(machine, "is_overridden", False):` in `_boot_settle_reconciliation_tick` tail with `if False:` | `test_a_med_2_boot_settle_override_dispatches_once_on_release` fails | CONFIRMED — override_set never dispatched after release; sibling "no override" test still passes; restored clean. |
| C-HIGH-1a | Neuter `apply_restored(` call in `manager._async_restore_house_state` | `test_c_high_1_restore_loads_sleep_and_sets_boot_restore_active` fails | CONFIRMED — machine stays AWAY, `boot_restore_active` False; restored clean. |
| C-HIGH-1b | Neuter `store.async_delay_save(` in `_on_persist_change` closure | `test_c_high_1_transition_triggers_debounced_save` + `test_c_high_1_heartbeat_callback_saves` fail | CONFIRMED — 2 tests FAIL (no debounced save on transition; no save on heartbeat tick); restored clean. |
| C-HIGH-1c | Neuter `await self._get_house_state_store().async_save(` in `async_stop` | `test_c_high_1_stop_hook_and_async_stop_flush_via_async_save` fails | CONFIRMED — `store.saves` list stays empty on stop; restored clean. |
| C-HIGH-3a | Replace boot-settle guard `if not self._boot_settle_done:` in `_dispatch_house_state_change` with `if False:` | `test_c_high_3_boot_settle_gate_suppresses_and_counts` fails | CONFIRMED — dispatch leaks under boot-settle; suppressed count never increments; restored clean. |
| C-HIGH-3b | Replace `if self.observation_mode:` gate in helper with `if False:` | `test_c_high_3_observation_mode_gate_suppresses` fails | CONFIRMED — dispatch leaks under observation mode; restored clean. |

Interpreter: `.venv-ha/bin/python`; `PYTHONDONTWRITEBYTECODE=1`; no
`.pyc` staleness risk.

### Suite baseline diff (no -n)

- **-k "presence or house_state or hvac or manager" name-diff vs
  `develop@d01ed874c`:** branch = 33 failures; develop = 33 failures.
  Δ = **0 new failure names.** Progression across this batch:
  original 36 -> 29 (after removing `async_test_home_assistant`) -> 0
  (after lazy `Store` import in `manager.py`, stdlib `timezone.utc` in
  `house_state.py`, D2 test wiring through the real
  `CoordinatorManager._wire_house_state_persistence`, and this fix-up
  round's 13 new tests being fully hermetic under FakeHass).
- **Historical note (kept for the review record):** the pre-fix-up
  ORDER-POLLUTION triage in this section previously argued the 29 fails
  were suite-hygiene artifacts. That claim is now moot — the root cause
  was `homeassistant.helpers.storage.Store` being imported at
  `manager.py` module scope, which pulled real HA helper modules into
  `sys.modules` and no-op'd the `sys.modules.setdefault` stubs used by
  `test_domain_coordinators.py` / `test_coordinator_diagnostics.py`.
  Lazy-loading `Store` via `_get_house_state_store()` closed the door.
- The new file passes 38/38 solo:
  `pytest test_house_state_restore_override.py -q` -> `38 passed`.
- The 33 develop-baseline failures (`datetime.utcnow()` tz-mixups in
  `test_presence_coordinator.py::TestGeofenceHandler` +
  `test_v47x_weather_manager.py::TestProviderHealth` etc.) reproduce on
  develop unchanged and are NOT touched by this cycle.

### Live (F9 — DAYTIME override, no night restart)

- With house at `home_evening` and `HOUSE_STATE_HEARTBEAT_S = 300`, call
  `ura.set_house_state` with `sleep`; wait one heartbeat period.
- Restart HA.
- After boot: `sensor.ura_house_state` reads `sleep`; HVAC bedroom presets
  at sleep values; no zone flip to Home; zero `house_state_change` rows in
  the URA activity log for the +15 min boot window (confirmed suppression
  under `boot_restore_confirmed`).
- Clear override via `ura.set_house_state auto`. Within one second: HVAC
  reverts, security day-arming, exactly one `house_state_change` row with
  `trigger=override_clear`. Arrester immune holds sunset (declared side
  effect — operator flagged).

### Post-deploy validation table (populate after live)

| # | Criterion | PASS/FAIL | Evidence |
|---|---|---|---|
| 1 | Restored SLEEP survives restart | TBD | TBD |
| 2 | Zero boot-window `house_state_change` under confirmed | TBD | TBD |
| 3 | Override set dispatches within 1 s | TBD | TBD |
| 4 | Override clear dispatches within 1 s | TBD | TBD |
| 5 | Heartbeat writes advance `saved_at` | TBD | TBD |

## Non-goals

- Zone sleep restore (out of scope — D0 trace proved the house-state signal
  drove the incident; zone persistence not required for this cycle).
- No new operator-visible entity; staleness + heartbeat are rung-1 consts.
- No change to inference logic apart from the R2-2 deferral during
  boot-settle when `_boot_restore_active` is True.
