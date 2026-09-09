# v5.100.2 — Energy-signal dispatches made thread-safe (off-loop async_write_ha_state)

**Type:** Hotfix (thread-safety correctness; control path unchanged).
**Tier:** 1 (3 sites, single bug class, no new feature). One adversarial review + orchestrator
re-grep. Card: `ENERGY-ENTITIES-UPDATE-DISPATCH-ERROR-1`.

## Why
Live HA logged, every energy refresh (~46×/5h + 3× at EC-ready), a hard error:

> `RuntimeError: Detected that custom integration 'universal_room_automation' calls
> async_write_ha_state from a thread other than the event loop` — at `time.py:186` (`_refresh`)
> and `switch.py:1221` (`_handle_ec_ready`).

HA 2026.x **escalated** off-loop `async_write_ha_state` from a warning to a raised error. The
energy decision cycle and the EC-ready path dispatched `SIGNAL_ENERGY_ENTITIES_UPDATE` /
`SIGNAL_ENERGY_COORDINATOR_READY` via HA's **loop-only** `async_dispatcher_send`, which invokes
connected callbacks synchronously in the caller's thread. The connected entity callbacks (the
onset-time TimeEntity, the EC sub-switches, and the number/sensor/binary_sensor/button
subscribers) all call `async_write_ha_state()` — so when the dispatch ran off the loop, every
subscriber tripped the guard. Log-polluting and a real thread-safety hazard.

## Root cause (verified, not assumed)
- Live traceback anchored the raising callbacks (`time.py:186`, `switch.py:1221`) and the
  `run_callback_threadsafe`/`future.result()` frames prove the callback executed off-loop.
- HA source contract (`homeassistant/helpers/dispatcher.py`, dev): `async_dispatcher_send` runs
  `hass.verify_event_loop_thread(...)` and calls subscribers directly (loop-only), while
  **`dispatcher_send` marshals via `hass.loop.call_soon_threadsafe(...)`** — safe from any thread.
- No other URA loop-only call (e.g. `async_create_task` in the same cycle body) errors, so the
  cycle body reaches the dispatch fine; only the dispatched entity writes trip the guard.

## What shipped
Swapped the loop-only `async_dispatcher_send` for the threadsafe `dispatcher_send` at the **three**
energy-signal sender sites:
- `domain_coordinators/energy.py:1138` — `SIGNAL_ENERGY_COORDINATOR_READY`.
- `domain_coordinators/energy.py:6553` — `SIGNAL_ENERGY_ENTITIES_UPDATE` (per-cycle refresh, the `_send` alias).
- `__init__.py:7217` — `SIGNAL_ENERGY_ENTITIES_UPDATE` (DP-enable options-apply refresh).

Callbacks now always run on the loop; the display refresh defers by one loop tick (harmless).
**Control path byte-identical** — only the display-refresh dispatch mechanism changed; no battery/
EVSE/pool decision logic touched.

## Test
`quality/tests/test_energy_dispatch_threadsafe.py` — three assertions, one per site, that each
dispatch uses the threadsafe `dispatcher_send` and not the loop-only variant. Mutation-anchored:
reverting any site to `async_dispatcher_send` turns the matching assertion RED (verified). Import-free
(reads source) so it needs no HA harness. No unit-level loop-thread detector exists, so the
falsifiable invariant is "these sites use the threadsafe API".

## Live validation — acceptance criteria (discriminating)
- **L1:** restart clean, config valid.
- **L2 (the fix):** after restart + one energy cycle (~5 min), the error_log shows **zero** new
  `async_write_ha_state from a thread other than the event loop` entries citing `time.py` or
  `switch.py`. Discriminator vs pre-fix: the pre-fix build logged ~12/hr steadily.
- **L3:** `sensor.ura_battery_strategy` and the onset-time entity still update (dispatch still
  reaches subscribers, just on-loop).

## Superseded by v5.100.3 (2026-09-08)

**This fix was necessary-but-INSUFFICIENT.** Live post-restart logs showed the RuntimeError kept
firing at the 5-min energy-cycle cadence (20:00:46 etc.) from the same `time.py:186` / `switch.py:1221`
sites. Root-cause re-diagnosis: HA's dispatcher runs a **non-`@callback`** sync target in the
executor thread regardless of sender — so the load-bearing fix is `@callback` on the two undecorated
targets (see `README_v5.100.3.md`). The threadsafe `dispatcher_send` senders shipped here were kept
as belt-and-suspenders.
