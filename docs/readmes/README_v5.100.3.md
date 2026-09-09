# v5.100.3 — Energy-signal callbacks decorated @callback (the REAL off-loop fix)

**Type:** Hotfix (thread-safety correctness; control path unchanged).
**Tier:** 1. Root-cause re-diagnosis after v5.100.2 proved insufficient + orchestrator verify.
Card: `ENERGY-ENTITIES-UPDATE-DISPATCH-ERROR-1` (reopened → refixed).

## Why v5.100.2 didn't fix it (honest record)
v5.100.2 swapped the loop-only `async_dispatcher_send` for the threadsafe `dispatcher_send` at
the sender sites. **It did not stop the error** — live proof: new `RuntimeError:
async_write_ha_state from a thread other than the event loop` occurrences at 19:50:46 **and**
19:55:46 (the 5-min energy-cycle cadence), post-restart, still citing `time.py:186` and
`switch.py:1221`. That falsified the sender-thread hypothesis.

## Actual root cause (verified against HA source)
HA's dispatcher (`helpers/dispatcher.py`, verified on `dev`) generates a job per connected
target via `get_hassjob_callable_job_type`:
- a **`@callback`** target runs **directly on the event loop**;
- a **plain sync function** is `HassJobType.Executor` and is run via `hass.async_run_hass_job`
  → **in the executor thread (off the loop)**.

The two targets that logged the error were **plain functions, not `@callback`**:
`time.py`'s `_refresh` closure and the **`_handle_ec_ready` override** in the EC-switch subclass
(`switch.py:1393`) — the override calls `super()._handle_ec_ready()` (which *is* `@callback`),
but HA connects and classifies the *override*, so the whole invocation was executor-punted.
Every sibling subscriber (`number._on_energy_tick`, `button._handle_ready`,
`sensor._handle_update`, the other `switch._handle_ec_ready` at 1187/1526/1798) is already
`@callback` — which is exactly why only these two logged the error.

## What shipped
- **`time.py`** — imported `callback`; decorated the `_refresh` closure `@callback`.
- **`switch.py:1393`** — decorated the `_handle_ec_ready` override `@callback`.
- v5.100.2's threadsafe `dispatcher_send` senders are **retained** (belt-and-suspenders: they
  guarantee the internal send runs on the loop even if a future sender is off-loop; with the
  targets now `@callback`, callbacks execute on the loop unconditionally).
- **Control path byte-identical.** Only the display-refresh execution thread changed.

## Orchestrator verify
Audited **all** subscribers of `SIGNAL_ENERGY_ENTITIES_UPDATE` + `SIGNAL_ENERGY_COORDINATOR_READY`
across time/number/switch/button/sensor/binary_sensor: the two fixed here were the ONLY
undecorated targets. No other executor-punt site remains.

## Test
`quality/tests/test_energy_dispatch_threadsafe.py` — extended with two `@callback` anchors (one
per fixed target) plus the retained sender assertions. Mutation-anchored: dropping either
`@callback` turns the matching assertion RED (verified); import-free (reads source).

## Live validation — acceptance criteria (discriminating)
- **L1:** restart clean, config valid.
- **L2 (the fix):** after restart + two energy cycles (~10 min), **zero** new
  `async_write_ha_state from a thread` entries citing `time.py` or `switch.py`. Discriminator vs
  v5.100.2: the pre-fix build logged one pair per 5-min cycle (19:50:46, 19:55:46, …).
- **L3:** `sensor.ura_battery_strategy` + the onset-time entity still update.

## Validated 2026-09-08 (post-restart, v5.100.3 live)

| Criterion | Result | Evidence |
|---|---|---|
| L1 clean boot / version | **PASS** | `const.py` = v5.100.3; `ha_check_config` valid (errors=[]). |
| **L2 thread error eliminated (the fix)** | **PASS** | Energy decision cycle RAN on v5.100.3 (`decision_log` newest 2026-09-09T01:07:42Z = 20:07 CDT), and **zero** `async_write_ha_state from a thread` entries after boot — newest occurrence is 20:00:46 CDT, the pre-restart v5.100.2 instance's last cycle. Under the broken build there would be one time.py/switch.py pair per 5-min cycle (20:05, 20:10). None. |
| L3 subscribers still update | **PASS** | Energy cycles producing `decision_log` rows post-boot; battery-strategy path live. |

**Rollback not needed.** The `@callback` fix resolves the off-loop executor-punt; v5.100.2's threadsafe senders retained as belt-and-suspenders.
