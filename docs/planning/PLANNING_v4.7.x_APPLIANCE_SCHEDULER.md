# B5: URA Appliance Scheduler — Cost-Reduction Deferral & Forecast-Aware Sprinklers

**Version:** 1.0
**Date:** May 5, 2026
**Status:** Ready to build (queued as v4.7.x; was v4.4.x)
**Renumbered:** 2026-05-06 from v4.4.x to v4.7.x in the post-v4.3.4 reshuffle that moved Battery Strategy v2 Overlay to v4.5.0 and Routine Awareness to v4.6.0.
**Depends on:** Energy Coordinator (v4.0.0+, TOU engine), Coordinator Manager v3.6+ (`register_coordinator`), URADatabase v4.2.x (write queue with batching + budgeting)
**Effort:** ~28-36 hours (D1-D6: ~22h core; D7-D8 sprinklers + provider-2: ~10h)
**Priority:** MEDIUM-HIGH — directly reduces utility cost; foundational for future appliance/water integrations

---

## Goal + Why Now

Defer flexible appliance starts (washers, dishwashers, washtowers) into the cheapest TOU window of the day, and skip Rainbird sprinkler runs when rain is forecast. The scheduler must be a clean platform — adding a new appliance brand should be a provider class, not a coordinator rewrite.

**Why now:**
- EC's `TOURateEngine.get_next_transition()` already exposes everything needed to schedule deferrals (line 211 of `energy_tou.py`); we are not blocked on EC changes.
- LG ThinQ + Rainbird are the two integrations the user already runs, and both expose stable HA service surfaces (`lg_thinq.set_delay_start` style, `rainbird.set_rain_delay`).
- Cost reduction is concrete and measurable (peak vs off-peak rate delta × kWh per cycle) — easy success criteria.
- Tier 2 review pattern is mature: 29 documented bug classes give a precise prevention checklist.

---

## Prior art reference

**`flashg1/SolarCharger`** (https://github.com/flashg1/SolarCharger) — HACS solar EV charging integration. Studied 2026-05-07. Worth reviewing for the **deadline-driven scheduling abstraction** ("next charge completion time" + 7-day per-day-of-week SOC target schedule + just-in-time start computation). The same shape applies to appliances: "complete by X time, optimize when within constraint." Adopt this pattern when adding deadline awareness to LG ThinQ cycles (e.g., "dishwasher must finish by 06:00 — defer start to whenever lets us land in cheapest TOU window while meeting deadline"). Also documents a "no-interference" mode for manual user control, anti-flap power-monitor duration thresholds, and per-load weighting/prioritization — all relevant patterns for B5.

## Design Principles

**1. Defer, don't interrupt.** Scheduler only acts on cycles that have not yet started. A running cycle is never paused, even if user was about to hit "start" during peak. (Mid-cycle interrupt is out of scope; some appliances tolerate it poorly and the user-visible disruption isn't worth the savings.)

**2. Provider plugin pattern (extensibility).** Adding Bosch / SmartThings / smart-plug-monitored appliances must require zero edits to `appliances.py`. Concrete providers live in `appliance_providers/*.py` and self-register.

**3. Source-of-truth = entity_id, not entity object.** LG ThinQ frequently disconnects/reconnects, replacing entity objects. The scheduler must hold only entity_id strings + service names, resolved fresh each call. Restart and reload survive transparently.

**4. Restart-survivable.** A pending deferral persisted to DB at write time is restored on `async_setup`, re-queued, and either resumed (still in future) or executed-immediately (window already arrived) or expired (window passed long ago, log + drop).

**5. Sprinklers are different.** They have only ONE deferral primitive (rain delay in days, not minutes). Forecast threshold is configurable. Rain delay only suppresses *future* schedules — active cycles are not interrupted (per Rainbird semantics).

**6. Fail-safe on missing inputs.** No TOU engine = pass-through (no deferral). No weather forecast = no skip. Stale forecast (> 6h old) = no skip. Provider unreachable mid-defer = log + drop deferral; do not retry indefinitely.

---

## ApplianceProvider Abstraction

A new package `domain_coordinators/appliance_providers/` containing:

- `base.py` — `ApplianceProvider` ABC and `ApplianceCapabilities` dataclass.
- `lg_thinq.py` — `LGThinQProvider` (washer / washtower / dishwasher).
- `rainbird.py` — `RainbirdProvider` (irrigation; uses `set_rain_delay`).
- `generic_power_sensor.py` — `GenericPowerSensorProvider` (no native control surface; only INFORMS, never DEFERS).
- `__init__.py` — `discover_providers(hass)` returns the registered list.

### `ApplianceProvider` ABC (interface only)

| Method | Purpose | Sync/Async |
|---|---|---|
| `provider_id: str` (classvar) | Stable string, e.g. `"lg_thinq"` | — |
| `is_present(hass) -> bool` | Is the underlying integration loaded? | sync |
| `enumerate_appliances(hass) -> list[ApplianceCandidate]` | Auto-discovery: query device registry by manufacturer/model | async |
| `get_remote_start_state(entity_id) -> RemoteStartState` | Is remote-start armed AND ready to receive a delay command? | async |
| `set_delay_start(entity_id, minutes: int) -> ProviderResult` | Issue the deferral. `minutes=0` = start now. | async |
| `cancel_delay_start(entity_id) -> ProviderResult` | User aborted — revert | async |
| `get_current_status(entity_id) -> ApplianceStatus` | `{idle, ready_to_start, delayed, running, complete, unavailable}` | async |
| `get_remaining_time(entity_id) -> int \| None` | Minutes left in current cycle (informational) | async |
| `register_state_listener(entity_id, callback) -> CallableUnsub` | Fires when status changes; uses `async_track_state_change_event` on entity_id | sync |

**`ApplianceCapabilities`** dataclass: `supports_delay_start: bool`, `supports_remote_start: bool`, `supports_pause: bool`, `delay_unit: Literal["minutes","days"]`, `max_delay: int`. Sprinkler provider returns `delay_unit="days"` and the coordinator translates accordingly.

**`GenericPowerSensorProvider`** is informational-only — `supports_delay_start=False`. Its job is to let the user *see* an appliance ran during peak hours so they learn to defer manually. It satisfies the extensibility goal without requiring a control surface.

**Open question:** Whether to ship LGThinQProvider relying on the official `lg_thinq` integration's `set_delay_start` (verify exact service name on user's HA), or fall back to `wash_set_delay_start` family naming. Flag for verification during implementation.

---

## Provider Discovery & Config

**Hybrid model:**

1. On config-flow entry to the Appliance Coordinator step, the flow runs `discover_providers()`, calls `enumerate_appliances()` on each, and produces a candidate list with checkboxes (defaulted ON).
2. User confirms / unchecks individual appliances and sets per-appliance preferences (target window, max delay, enabled).
3. Selected list persisted to CM entry `options["appliance_scheduler"]["appliances"]` keyed by **entity_id**, never by device object.

This preserves auto-detect convenience while letting the user opt out (e.g., user might not want the basement washer scheduled because it serves a different rhythm).

---

## TOU "Minutes Until Off-Peak" Source

EC's existing `TOURateEngine.get_next_transition()` returns `{next_period, hours_until, transition_hour}` in whole hours. We need minute precision.

**Decision:** Extend `energy_tou.py` with `get_minutes_until_period(target_period: str, now=None) -> int | None`. Implementation walks the same `transitions` list but computes minute-precise delta from `now` to the next transition where `t_period == target_period`. Returns `None` if no off_peak window in the next 24h (shouldn't happen for PEC schedule, but defensive).

**Why extend EC, not duplicate logic in Appliance Coordinator:**
- Avoids Bug Class #22 (enum mismatch): same `_VALID_PERIODS` set, same period-name aliases.
- Keeps TOU rate file ownership in EC.
- Appliance Coordinator just calls `energy_coord.tou_engine.get_minutes_until_period("off_peak")`.

EC must already be set up at this point (registration order in `__init__.py` line 1461 confirms EC registers before HVAC; Appliance can register after EC similarly). Guard with `if energy_coord is None or energy_coord.tou_engine is None: skip deferral, log once`.

---

## State Machine Per Deferral

```
   user/integration says "ready_to_start"
                |
                v
        EVALUATING ────(provider unreachable)───> DROPPED
                |
                v (TOU off-peak? → minutes=0; else compute)
        SCHEDULING
                |  (provider returns OK)
                v
        ARMED ──(user cancels at appliance)──> CANCELLED
        |  |
        |  └──(integration goes unavailable > 30m)──> DROPPED + notify
        |
        (delay timer fires)
                v
        EXPECTING_RUN ──(no run within 15m)──> ANOMALY (log; do not retry)
                |
                v
          RUNNING ──> COMPLETE
```

State, target_run_time, provider_id, entity_id, and reason are persisted to URADatabase on each transition.

---

## Deliverables

### D1: ApplianceProvider abstraction + LGThinQProvider

**What:** Define `ApplianceProvider` ABC, `ApplianceCapabilities`, `ApplianceCandidate`, `ApplianceStatus` enum, `RemoteStartState` enum, `ProviderResult` dataclass. Implement `LGThinQProvider` using HA service calls, identifying eligible entities by manufacturer="LG Electronics" + model regex match. Expose `enumerate_appliances` returning candidates for the user's 2 washers, 2 washtowers, 2 dishwashers.

**Bug class prevention:**
- #22: `ApplianceStatus` and `RemoteStartState` enums must be StrEnum; no string-comparison handlers reading raw values without going through `.value`.
- #29: every status string the coordinator branches on must have a populator path tested.

### Acceptance Criteria
- **Verify:** Config flow lists exactly the 6 LG appliances on user's system with auto-detected names.
- **Verify:** `LGThinQProvider.set_delay_start(entity_id, 90)` issues exactly one service call; idempotent if called twice with same value.
- **Sensor:** `sensor.ura_appliance_coordinator_provider_status` exposes per-provider availability.
- **Test:** `test_lg_thinq_enumerates_six_appliances`, `test_lg_thinq_set_delay_start_idempotent`, `test_lg_thinq_handles_service_call_exception`.
- **Live:** With one washer in remote-start mode, manual service call from Appliance Coordinator delays start by 60m; UI on washer reflects.

---

### D2: Appliance Coordinator core (`appliances.py`)

**What:** New `ApplianceCoordinator(BaseCoordinator)` in `domain_coordinators/appliances.py`. Priority: 25 (between Comfort=20 and Energy=30; see `manager.py` register order). Subscribes to provider state listeners (entity_id-stable), holds the deferral state machine, calls EC's TOU engine for off-peak math, dispatches `SIGNAL_APPLIANCE_DEFERRED` and `SIGNAL_APPLIANCE_STARTED` (new constants in `signals.py`).

**Key implementation notes:**
- `_pending_tasks: set[asyncio.Task]` mirrors HVAC pattern (line 160). All `hass.async_create_task` calls add+discard.
- All `async_track_time_interval` and `async_call_later` handles stored in `self._unsub_listeners` and unsubscribed in `async_teardown` — Bug #19.
- `_register_state_listeners()` called from `async_setup`, NOT `async_added_to_hass` — Bug #1.
- Config read via `_refresh_config()` (Bug #14 prevention) at top of every public coordinator entry point. Config = `{**cm_entry.data, **cm_entry.options}` — Bug #2.

### Acceptance Criteria
- **Verify:** Coordinator registers in CM, appears in `coordinator_manager.coordinators`, and survives a CM `async_stop`/`async_start` round-trip.
- **Sensor:** `sensor.ura_appliance_coordinator_pending_deferrals` shows count of ARMED state machines.
- **Sensor:** `sensor.ura_appliance_coordinator_savings_today` shows estimated $ saved (configured rate delta × cycle kWh estimate from provider, defaulted to 1.5 kWh if unknown).
- **Test:** `test_appliance_coordinator_setup_teardown_idempotent`, `test_pending_tasks_cancelled_on_teardown` (Bug #19), `test_config_changes_take_effect_without_restart` (Bug #14).
- **Live:** Coordinator appears in Coordinator Manager device list; teardown does not leave hanging timers (verify with `hass.helpers.event` introspection).

---

### D3: TOU "minutes until off-peak" extension on EC

**What:** Add `TOURateEngine.get_minutes_until_period(target_period, now=None)` and `get_period_at(when, now=None)`. Add a new attribute `minutes_until_off_peak` on `sensor.ura_energy_coordinator_tou_status` for visibility. Pure additive change to EC, no behavior modifications elsewhere.

**Bug class prevention:**
- #11: `now` must be normalized via `dt_util.now()` and never compared across timezones.
- #22: `target_period` validated against `_VALID_PERIODS`; raises ValueError on unknown.

### Acceptance Criteria
- **Verify:** At 3:30pm with peak starting at 4pm and ending at 9pm in PEC summer, `get_minutes_until_period("off_peak")` returns `330` (5.5 hours = 5h 30min).
- **Verify:** During off_peak, returns `0`.
- **Test:** `test_minutes_until_off_peak_during_peak`, `test_minutes_until_off_peak_during_off_peak_returns_zero`, `test_minutes_until_off_peak_invalid_target_raises`, `test_minutes_until_off_peak_dst_transition` (Bug #11).
- **Live:** Sensor attribute matches manual computation against TOU JSON file.

---

### D4: Deferral persistence + restart resilience

**What:** New URADatabase methods `save_appliance_deferral(deferral_id, payload_json)`, `load_pending_deferrals()`, `delete_appliance_deferral(deferral_id)`, and `cleanup_appliance_deferrals(retention_days=14)`. Coordinator persists every state-machine transition. On `async_setup`, loads pending rows and re-queues each according to current state:
- Stored target_run_time still in the future → `async_call_later(delay_seconds, _execute_deferred)`.
- Target time within ±15 min of now → execute immediately.
- Target time more than 1 hour past → mark EXPIRED, log, drop.

Cleanup method is registered in nightly maintenance schedule (Bug #27 — every cleanup must be scheduled).

**Bug class prevention:**
- #21: Deserialize timestamps with `dt_util.parse_datetime()`, NOT `datetime.fromisoformat()`.
- #25: All deletions use `WHERE rowid IN (... LIMIT 1000)` batched.
- #27: New `cleanup_appliance_deferrals` MUST be added to `__init__.py` nightly maintenance op list. Add a regression test that scans `database.py` for `cleanup_*` and asserts each is referenced in nightly maintenance.
- #29: Nightly task is already budget-aware (v4.2.9 fix); add `cleanup_appliance_deferrals` to the rotation list.
- #10: Restart restore is the whole point of D4.

### Acceptance Criteria
- **Verify:** Defer a washer 4 hours, restart HA after 1 hour, verify deferral resumes and fires at the original target time (±60s).
- **Verify:** Defer a washer 30 min, kill HA process, restart 2 hours later — deferral marked EXPIRED, no spurious service call.
- **Sensor:** `sensor.ura_appliance_coordinator_restored_deferrals` increments on each successful restore.
- **Test:** `test_persist_and_restore_pending_deferral`, `test_expired_deferral_dropped_on_restore`, `test_timestamp_naive_aware_safe` (Bug #21), `test_cleanup_appliance_deferrals_scheduled` (Bug #27).
- **Live:** `pkill -9` on HA, restart, verify washer with pending defer either fires or expires correctly.

---

### D5: Integration reload resilience

**What:** Coordinator listens to `homeassistant.exceptions.HomeAssistantError`-class transient unavailability. State listeners use `async_track_state_change_event(hass, [entity_id], callback)` rather than holding entity object refs. When LG ThinQ reloads:
- entity_id remains the same; new entity object replaces old one transparently.
- Coordinator does NOT re-issue service calls — the `set_delay_start` already accepted by the appliance is preserved on the appliance itself.
- If the appliance has its own delay state (LG appliances do), no re-arming needed. Provider's `get_remote_start_state` re-checks on next reconciliation.
- Reconciliation: every 5 min, walk pending deferrals; for each, call `provider.get_current_status()`. If status disagrees with state machine, reconcile (log conflict, prefer appliance truth).

**Bug class prevention:**
- #20: Never call `async_update_entry` from within Appliance Coordinator's options flow on another entry. If linking to EC config, defer with `hass.async_create_task` after current save.
- #22: Reconciliation compares `ApplianceStatus` enum `.value`, not raw string literals.

### Acceptance Criteria
- **Verify:** Disable+enable LG ThinQ integration; pending deferral remains in URA state, no double service call after reload.
- **Verify:** Hard-reload Appliance Coordinator entry; pending deferral state restored correctly.
- **Sensor:** `sensor.ura_appliance_coordinator_reconciliation_count` increments on each 5-min walk.
- **Test:** `test_provider_unavailable_during_arm_drops_gracefully`, `test_no_double_service_call_on_reload`, `test_state_listener_uses_entity_id_not_object`.
- **Live:** Watch logs during LG ThinQ reconnect; coordinator must log reconciliation but issue no service call.

---

### D6: Failure-mode state machine + observation mode + signals

**What:** Wire up the full state machine described above, plus:
- Observation mode gate at DISPATCH (Bug #23): check `_get_signal_config("appliance_scheduler_response", default=False)` before any state mutation or service call.
- Coordinator-Manager-level observation mode also suppresses (re-use existing CM observation flag).
- Dispatch new signals `SIGNAL_APPLIANCE_DEFERRED`, `SIGNAL_APPLIANCE_RUNNING`, `SIGNAL_APPLIANCE_COMPLETE` for downstream consumers (notification manager could surface "$X saved today").
- Failure handling table:

| Failure | Response |
|---|---|
| Appliance unreachable mid-defer | Wait 30 min for reconnect; if still unreachable → DROPPED, log, NM notification |
| User cancels at appliance | Detected via `get_current_status() == "idle"` during reconciliation → CANCELLED |
| EC TOU sensor unavailable | Skip the deferral entirely (start now) — log once, count in `defer_skipped_no_tou` |
| Weather forecast stale (>6h old) | For sprinklers only: skip the rain-skip decision (let cycle run normally) |

**Bug class prevention:**
- #23: Every dispatch site of new signals checks observation mode BEFORE side effects.
- #28: Any `entry.add_update_listener` registration is `async def`. Lint test from QC #28 must already cover this; add a new test ensuring this file passes.
- #24: Any lambdas at module/init scope (e.g., for lazy registry lookup) reference only module-level imports.

### Acceptance Criteria
- **Verify:** With observation mode ON, deferral logs intent but never calls services.
- **Verify:** EC unavailable simulated → deferrals start immediately with reason="no_tou".
- **Sensor:** `sensor.ura_appliance_coordinator_state_machine_breakdown` exposes counts in each state.
- **Test:** `test_observation_mode_blocks_dispatch_at_origin` (Bug #23), `test_no_sync_update_listener` (Bug #28 lint), `test_lambdas_use_module_imports` (Bug #24).
- **Live:** Toggle observation mode in CM; verify zero appliance state changes for 24h.

---

### D7: RainbirdProvider + forecast-aware skip

**What:** `RainbirdProvider` implements `set_delay_start(entity_id, minutes)` by translating to days (ceil(minutes/1440)) and calling `rainbird.set_rain_delay`. Capability: `delay_unit="days"`, `max_delay=14`. Forecast logic in coordinator (NOT provider — it's policy):

1. Configurable per-controller threshold (default: rain probability ≥ 60% within next 24h, OR forecast precipitation ≥ 0.10 inches).
2. Configurable weather entity (defaults to user's `weather.phalanxmadrone`).
3. Coordinator calls `weather.get_forecasts` service (using same pattern as EC line 1870) once per evaluation; result cached for 30 min (Bug #26 — DB/service read TTL).
4. If threshold met: call `set_rain_delay` for `ceil(forecast_window_days)`. Coordinator does NOT pause active cycles (Rainbird semantics + user requirement).
5. If forecast unavailable or stale (> 6h since fetched): no skip decision, let normal schedule run.

**Bug class prevention:**
- #26: Forecast cache TTL 30 min; use `time.monotonic()`.
- #11: Forecast timestamps from HA may be UTC; convert to local before any `.date()` comparison.
- #8: Forecast response is dynamic — guard `isinstance(response, dict)` and `isinstance(forecasts, list)` before access.

### Acceptance Criteria
- **Verify:** With mocked forecast showing 80% rain probability tomorrow, coordinator issues `set_rain_delay` of 1 day on next decision cycle.
- **Verify:** With forecast < threshold, no service call.
- **Verify:** Active sprinkler cycle is NOT interrupted by skip decision.
- **Verify:** Forecast service failure does not crash coordinator; logged as warning, no skip.
- **Sensor:** `sensor.ura_appliance_coordinator_sprinkler_skips_today` increments on skip.
- **Test:** `test_skip_when_high_rain_probability`, `test_no_skip_when_low_probability`, `test_no_skip_when_forecast_stale`, `test_active_cycle_not_interrupted`, `test_forecast_response_dict_guards` (Bug #8).
- **Live:** Wait for next forecast >60% rain day; verify rain delay set; no zone interruption mid-cycle.

---

### D8: GenericPowerSensorProvider (extensibility proof)

**What:** Read-only provider that watches a configured `sensor.*_power` entity and emits state transitions when power crosses a threshold (start/stop). `supports_delay_start=False`, so coordinator records cycles for reporting but never tries to defer. Demonstrates the abstraction works for a fundamentally-different shape of integration. Future Bosch / SmartThings providers will follow the same skeleton with control surfaces enabled.

### Acceptance Criteria
- **Verify:** Configure a generic power sensor for the gas dryer; coordinator logs each cycle with start/stop times and energy.
- **Sensor:** `sensor.ura_appliance_coordinator_unmanaged_cycles_today` shows cycles run during peak (educational visibility for the user).
- **Test:** `test_generic_provider_no_defer_attempt`, `test_generic_provider_detects_cycle_via_power_threshold`.
- **Live:** Run a dryer cycle; URA logs and reports it without trying to control it.

---

## Implementation Order + Dependencies

```
D3 (TOU minutes-until)  ── independently testable; ship even if rest delays
D1 (Provider ABC + LG)  ── unblocks D2
D2 (Coordinator core)   ── needs D1 + D3
D4 (Persistence)        ── needs D2
D5 (Reload resilience)  ── needs D2
D6 (State + observation)── needs D2; ties D4+D5 together
D7 (Rainbird + forecast)── parallel after D2; uses D6 dispatch model
D8 (Generic power)      ── parallel after D1; demonstrates ABC
```

**Ship plan:** D1+D2+D3+D4+D6 as v4.7.0 (LG washers/dishwashers/washtowers cost-deferral). D5 hardening as v4.7.1. D7 sprinkler skip as v4.7.2. D8 (generic provider) as v4.8.0 once a real third-party device is being integrated.

---

## Estimated Line Counts

| Deliverable | Production Code | Test Code | Config Flow |
|---|---|---|---|
| D1 (provider ABC + LG) | ~280 (`appliance_providers/base.py` + `lg_thinq.py`) | ~180 | ~40 |
| D2 (coordinator core) | ~360 (`appliances.py`) | ~220 | ~80 |
| D3 (TOU extension) | ~40 (`energy_tou.py`) | ~70 | 0 |
| D4 (persistence) | ~140 (`database.py` + coordinator) | ~150 | 0 |
| D5 (reload resilience) | ~80 (coordinator) | ~120 | 0 |
| D6 (state machine + signals) | ~120 (`appliances.py` + `signals.py`) | ~140 | ~30 |
| D7 (Rainbird + forecast) | ~220 (`appliance_providers/rainbird.py` + coord) | ~180 | ~50 |
| D8 (generic power) | ~140 (`appliance_providers/generic_power_sensor.py`) | ~90 | ~40 |
| **Total** | **~1380 lines** | **~1150 lines** | **~240 lines** |

---

## Review Protocol

**Tier 2: Feature Cycle** (new coordinator + cross-coordinator EC dependency + new persistence + provider plugin layer)

1. **Review 1 (Core A):** Bug class prevention audit:
   - #1 (lifecycle): Coordinator uses `async_setup`, never `async_added_to_hass`.
   - #2/#14 (config staleness): `_refresh_config()` at top of every entry point.
   - #19 (untracked tasks): grep `async_create_task` in `appliances.py` and `appliance_providers/*.py`; every match must `add` to `_pending_tasks`.
   - #20 (concurrent reload race): no `async_update_entry` calls from this coordinator's options flow into other entries.
   - #21 (datetime parsing): all DB-restored timestamps via `dt_util.parse_datetime`.
   - #22 (enum mismatch): `ApplianceStatus`, `RemoteStartState`, TOU period strings all enum-driven.
   - #23 (observation mode): grep all `async_dispatcher_send` for new signals; each preceded by observation-mode check.
   - #24 (lambda scope): module-level `from ..const import DOMAIN as _DOMAIN`.
   - #25 (DELETE batching): `cleanup_appliance_deferrals` uses LIMIT batching.
   - #26 (DB/service cache): forecast service call cached 30 min via `time.monotonic()`.
   - #27 (orphaned cleanup): `cleanup_appliance_deferrals` registered in nightly maintenance ops list AND covered by lint test.
   - #28 (sync update_listener): all `add_update_listener` registrations are `async def` (lint test from QC #28 covers).
   - #29 (sensor populator): every new `sensor.ura_appliance_coordinator_*` has a populator path verified by test.

2. **Review 2 (Core B):** Race conditions specific to this coordinator:
   - Restart-during-defer: persisted state versus in-memory state. Property: at most one outstanding deferral per appliance at any time.
   - LG ThinQ reload during ARMED: no spurious `set_delay_start` re-issue.
   - User cancels at appliance during ARMED: reconciliation detects within 5 min, transitions to CANCELLED, dispatches signal once.
   - Rainbird: rain delay not set twice for same forecast event (idempotency on day boundary).

3. **Deploy via `/deploy`** — full URA pipeline.

4. **Live validation (7 days):**
   - Week 1: D1+D2+D3+D4+D6 — verify ≥ 80% of weekday washes deferred to off-peak.
   - Verify `sensor.ura_appliance_coordinator_savings_today` aligns with hand calculation.
   - Verify zero stale-task warnings in HA log.
   - After D7: verify rain-skip fires correctly on next forecasted rain day.

---

## What's NOT in This Plan

- **Microwave & oven scheduling.** Both are immediate-use devices; no remote start, no value in deferring (cycle is < 30 min and user-triggered at meal time).
- **Gas dryer active control.** Gas dryer has no remote-start interface and the marginal cost (gas only, no heavy electric draw) doesn't justify control complexity. D8 covers it informationally via GenericPowerSensorProvider.
- **Mid-cycle interrupt / pause.** Pausing a running washer mid-cycle is destructive (wet clothes, water sitting). Not worth small TOU savings. Out of scope by user requirement.
- **Demand-response (utility-driven event).** Different signal flow (utility API → response window). Could be a future B-series after this lands.
- **Consumption forecasting per appliance.** EC's forecaster handles whole-house; per-appliance models require training data that doesn't exist yet. Future BACKLOG item.
- **Sprinkler zone-level rain skip.** Rainbird's rain delay applies to all zones. Per-zone moisture-based skip would require soil sensors per zone (not installed). Skipped from scope.
- **Pause-and-resume across TOU boundaries.** A 3-hour wash that starts at 3pm would run into peak. We do NOT auto-pause. Provider scheduling (delay-start) handles future cycles only; this is the user's intentional trade-off (cycle integrity > squeezing every minute into off-peak).

---

## Open Questions (Flag for Implementation)

1. **Exact LG ThinQ service names** for `set_delay_start` on user's HA instance. Must verify via `hass.services.async_services()` introspection during config-flow — the `lg_thinq` HACS integration's surface has changed across versions. Provider should query HA service registry rather than hard-coding.
2. **Rainbird controller entity model:** Is the user running the official `rainbird` HA integration, or a custom HACS one? Service name differs (`rainbird.set_rain_delay` vs `irrigation_unlimited.*`). Verify before D7.
3. **CM observation mode flag name:** Need to confirm exact key in CM options (likely `observation_mode` but the existing coordinators check various keys). Inspect during D6 implementation, mirror what HVAC does.
4. **Whether to share the URADatabase schema migration approach** with energy state tables, or use HA `Store` helper. Recommendation: URADatabase, because batching/cleanup/budgeting infrastructure already exists; HA `Store` lacks per-row maintenance. Final call deferred to D4 implementation.
5. **Default cycle kWh estimates** for savings calculation if provider doesn't expose energy: use 1.5 kWh (washer), 2.5 kWh (dishwasher), 3.5 kWh (washtower). Should be configurable per-appliance with these as defaults — confirm during D2 config flow.
