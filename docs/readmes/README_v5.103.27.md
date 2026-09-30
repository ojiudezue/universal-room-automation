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

## Operator decisions pending

Both are single-line module-constant flips in `house_state.py`:

1. **`HOUSE_STATE_OVERRIDE_SURVIVES_RESTART`** — default **`True`** (plan
   F7 recommendation). If the operator wants overrides to be strictly
   ephemeral, flip to `False`; the restore path will drop `override` from
   the loaded payload.
2. **`HOUSE_STATE_OVERRIDE_ENDS_ARRESTER_HOLDS`** — default **`True`**
   (documents current behaviour: `hvac_override.py:903 sunset_immune_holds`
   fires on every `SIGNAL_HOUSE_STATE_CHANGED`, and D2 now dispatches on
   overrides). Constant is documentation-only in this cycle — the arrester
   sunset already fires; flipping to `False` would require a companion
   gate in `hvac_override.py` (not built in this cycle).

Surface these two questions at the pre-deploy checkpoint.

## Acceptance criteria (prospective — populate at Live Validation)

### Unit / integration (run pre-deploy)

- Machine restore round-trips SLEEP + fresh `saved_at` -> `_state==SLEEP`,
  `_boot_restore_active==True`, `_state_since` re-armed.
- Stale / disabled / corrupt / missing records -> AWAY default with
  `_boot_restore_active==False`.
- Heartbeat invariant: `HOUSE_STATE_HEARTBEAT_S <=
  HOUSE_STATE_RESTORE_MAX_STALE_S // 3` (meta-test).
- Persist hook fires on `transition`/`force_state`/`set_override`/
  `clear_override`.
- Dispatch hook: F6 four idempotence cases pass (see
  `test_house_state_restore_override.py::test_set_override_dispatches_*` +
  `test_transition_clears_override_but_hook_suppressed`).
- Real Store I/O round-trip via `pytest-homeassistant-custom-component`'s
  `async_test_home_assistant` (F11).
- Mutation drill: neuter `_fire_persist_change` in-process; every persist
  test flat-lines to zero calls (proves single-site load-bearingness).
- Memory-writer boot-suppression vocab: `boot_restore_confirmed` suppresses;
  `boot_restore_diverged` and `boot_settle_release` emit rows.

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
