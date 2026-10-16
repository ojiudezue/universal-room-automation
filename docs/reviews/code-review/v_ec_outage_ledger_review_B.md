# EC Outage Ledger (Stage L): Review B (integration, async/lifecycle, signal chain)

Branch `worktree-agent-aa2c92f9aca51a4f2`, commits 4e0367803..ea7999889. I verified the base b003a64cd with `git merge-base`.
HVAC/presence state-of-play docs were not read; they do not apply because the cycle touches neither area.

## Verdict: FIX-REQUIRED (1 HIGH)

## Findings

### B-HIGH-1: in production the sweep timer callbacks run in an executor thread, so the cloud sweep never runs
Bug class: async lifecycle / thread-safety. The tests use mocked timer helpers, which hides this.

- **Where:** `energy_outage_ledger.py`. `_spawn_sweep` (line ~458) and `_on_initial` (line ~482) are plain `def` methods with no `@callback` decorator.
- **What happens:** both are passed to `async_call_later` / `async_track_time_interval`.
  - Those helpers wrap them in `HassJob` (`helpers/event.py:1611-1614`).
  - `get_hassjob_callable_job_type` (`core.py:347-360`) classifies a non-coroutine function without `@callback` as `HassJobType.Executor`, so the callback runs in a worker thread.
  - In that thread, `self.hass.async_create_task(self.sweep())` reaches the thread check (`core.py:768-771`). The check calls `report_non_thread_safe_operation`, and for custom integrations that is set to `ReportBehavior.ERROR` (`helpers/frame.py:415-426`), so it raises.
- **Result:**
  - The first sweep at 300 s and every 24 h sweep after it raise in the executor. An error is logged and no `witness="cloud"` row is ever written.
  - D-L2(i), the primary outage witness, is dead on arrival.
  - `_sweep_task` is also read and written from that thread, so the "one sweep at a time" guard is racy.
  - The decision cycle is not harmed: the callback runs off-loop and the timer is separate from the tick.
- **Why tests are green:** `test_ec_outage_ledger.py:560-575` monkeypatches `async_call_later` / `async_track_time_interval` and calls the stored callback directly from the loop (`handles[0][2](None)`). No real HassJob dispatch happens.
- **Fix:**
  - Decorate `_spawn_sweep` and `_on_initial` with `homeassistant.core.callback`.
  - Add a test that does one of these:
    - asserts `is_callback(led._spawn_sweep)` and `is_callback(led._on_initial)`, or
    - better, uses the real `async_call_later` plus `async_fire_time_changed` with the `hass` fixture and checks that a cloud row is written.

### B-MED-1: rows bypass the `_write_queue`; each row opens its own connection
Bug class: write-path contract (behaviour inherited from an existing DAO).

- **Where:** `_emit` → `db.log_activity` (`database.py:6256-6290`).
- **Detail:** `log_activity` opens a direct `async with self._db()` connection plus a commit for every row. It does not use the serialized write queue, and the plan's description of the writes as going "through the write queue" is wrong.
- **Contract:** this is the same contract as `_record_reserve_dispatch`, so it is not a regression. It is fire-and-forget, so the tick never awaits it.
- **Burst size:** the first tick after boot or reload with N alerts in the feed spawns N concurrent single-row write tasks. N is small in practice (typically fewer than 10 alerts). This is acceptable, but correct the plan/README wording. A burst of a few rows is not a stall risk.

### B-LOW-1: `nws_alert` rows are written again on every CM reload or restart, and retained forever
`OutageLedger` is built in `EnergyCoordinator.__init__` (`energy.py:~797`). Each reload creates a fresh, empty `_seen_alerts`, so every active alert is logged again.

- This matches the plan's documented "per boot" semantics.
- The rows are prune-exempt (`ACTIVITY_LEDGER_RETAINED_ACTIONS`), so a restart storm (8 per night has happened before) multiplies the permanent rows. For example, 3 active alerts × 8 restarts = 24 rows.
- That is still inside the ~1,000 rows/yr budget, but consider seeding `nws_alert` keys from the DB the way the cloud leg is seeded.

### B-LOW-2: a failed DB seed is never retried
`_seed_cloud_seen` sets `_cloud_seeded = True` before it queries (line ~343). If that query throws (for example at boot under write-queue pressure), the boot never seeds, and a later sweep in the same boot can write cloud rows that the previous boot already wrote. Fix: set the flag only after the query succeeds.

## Cleared (holds because…)

| Concern | Status | Evidence |
|---|---|---|
| Hook cannot raise into or delay the decision cycle | HOLDS | `energy.py` `_outage_ledger_tick` is wrapped in a full `try/except Exception`. It is synchronous and makes no `await`. All reads are in memory: `hass.states.get`, `_inclement_config` (CM options read), `_read_nws_alerts` (`energy_battery.py:2640`, a states read), and `_grid_outage_active` (`energy_write_verify.py:1821`, a states read). `record_tick` guards each pass. There is no file or network I/O on the tick. |
| Hook placement | HOLDS | It sits after `determine_mode` and before the first `await` (~6455). It is skipped only if `determine_mode` itself raises, which is acceptable. |
| Byte-identical reserve and inclement behaviour | HOLDS | The `energy.py` diff contains only `__init__` construction, `_arm_outage_ledger()` in `async_setup`, the tick call, three new methods, and the teardown cancel. No reserve, inclement, or battery state is written; the hook only reads `_last_inclement_decision{,_at}` and `battery_soc`. The `database.py` change is additive: the `action` filter defaults to None, and the prune exemption is appended to both tiers. |
| Arm idempotence and teardown cancel | HOLDS once B-HIGH-1 is fixed | `arm()` checks each unsub for None. `cancel()` unsubs both timers, cancels the in-flight task, and is safe to call twice. It is wired into `async_teardown`, which is exercised by a test with the real teardown method. On reload, the old instance is cancelled and the new instance arms its own timers. |
| Calendar missing or unavailable at boot | HOLDS | The calendar is resolved from the registry, which is persisted, so it is present even before the integration loads. With 0 or more than 1 match, `resolve_calendar` returns None and the warning is logged once (`_unresolved_warned`). If the entity state is `unavailable`, the sweep logs at debug, writes nothing, and the next 24 h sweep's 48 h lookback still covers the gap. There is a 30 s `wait_for` timeout, and CancelledError is re-raised. |
| Seed vs first sweep race | HOLDS | The seed runs inside the sweep, before any emit, and `_spawn_sweep` refuses to start a second sweep while one is running. Prior-boot rows were committed synchronously by the direct-connection DAO, so there is no queue backlog to lose. Seed ordering is `ORDER BY id DESC LIMIT 1000`, and a 72 h window of `grid_outage` rows will be far below that. |
| Alert seen-set semantics | HOLDS | A key is pruned only once it has left the feed AND its end has passed or is unknown. A non-list feed (unavailable) returns early without pruning, so a feed blip does not cause re-logging. The cap of 500 evicts only keys that are not in the current feed. A key is added only after `_emit` succeeds, so a no-database tick retries later. |
| `grid_status` derivation | HOLDS | Checked live: `switch.enpower_482348004678_grid_enabled` maps to `binary_sensor.enpower_482348004678_grid_status`, and both exist; both are currently `unavailable`, which reads as None and keeps the leg inert. Any non-matching entity id skips derivation. A None reading never changes the baseline, and the first reading only sets the baseline. |

## Must-fix
1. B-HIGH-1: add `@callback` to `OutageLedger._spawn_sweep` and `_on_initial`, plus a test that drives a real HassJob (or at least asserts `is_callback`).

## Should-fix
- B-LOW-2: set `_cloud_seeded` only after the seed query succeeds.
- B-MED-1: correct the "write queue" wording in the plan/README.
