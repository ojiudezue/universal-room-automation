# B5: URA Appliance Coordinator v3 — Cost-Deferral, Interrupt-at-Start, PWA-Consumable Surfaces

**Version:** 3.0 (2026-05-23; staleness patch 2026-05-25)
**Status:** Ready to build (queued as v4.7.x).
**Supersedes:** `PLANNING_v4.7.x_APPLIANCE_SCHEDULER_v2.md` v2.0 (2026-05-19). v1.1 and v2.0 retained for history.
**Depends on:**
  - Energy Coordinator (TOU engine at `domain_coordinators/energy_tou.py`). v4.6.8 reconciliation surface (zone/house `cost_today_dollars`) **shipped 2026-05-18** — met dependency. D10 dashboard hooks consume these alongside appliance savings. Canonical rate API verified live (2026-05-25): `EnergyCoordinator.current_effective_rate` (property, `energy.py:3552`) for "now"; `TOURateEngine.get_effective_import_rate(now=...)` (method, `energy_tou.py:194`) for arbitrary instants (base + delivery + transmission).
  - Coordinator Manager v3.6+ (`register_coordinator` at `domain_coordinators/manager.py:236`)
  - URADatabase v4.6.7+ (write queue with batching + budgeting; `anomaly_log` NOT NULL-relaxed at v4.6.7 — interrupt-path anomalies CAN write partial metric columns now)
  - URA Dashboard PWA v6.0+ (separate repo at `~/Code/ura-dashboard-pwa/`; reads URA via HA WebSocket through `useUraSensor` hooks — see Dashboard Hooks section)
**Effort estimate:** ~36-46h (unchanged from v2.0; the PWA contract section adds no production code, only attribute-shape discipline)
**Priority:** MEDIUM-HIGH

---

## Why v3 (what's changed since v2.0)

v2 was written 2026-05-19, four days before this revision. Three concrete shifts justify a v3 rather than a v2-patch:

1. **Dashboard target changed from "v5.0+ HA panel" to "v6.0 standalone PWA."** Per `project_pwa_v6_pivot.md` (decision logged 2026-05-21), URA dropped the `panel_custom` + hakit path and shipped a standalone PWA at `https://ura.phalanxmadrone.com`, separate repo at `~/Code/ura-dashboard-pwa/`. v2's "Dashboard v5.0+ consumes the same surfaces" language assumed the panel-bundled-with-URA model. v3 re-grounds the dashboard contract against the PWA's actual hook layer at `/Users/okosisi/Code/ura-dashboard-pwa/src/data/useUraSensor.ts`:
   - Hooks subscribe to HA WebSocket via Zustand store; no privileged DB reads.
   - Contract is `{ state, loading, unavailable, attributes, last_updated }` per `UraSensorReadout`.
   - `useUraSensorAttrs<T>` is an UNCHECKED cast — coordinator must guarantee attribute shape stability.
   - Strings ("unknown", "unavailable", "") are treated as `unavailable=true`. Coordinator should NOT emit those as "valid" values for the int/float parsers.

2. **v4.6.8 EC TOU rate reconciliation + zone/house cost surface SHIPPED 2026-05-18** (met dependency). The Appliance Coordinator's `savings_today_dollars` sensor rides the v4.6.8 cost-vocabulary — consumes `TOURateEngine.get_effective_import_rate(now=projected_run_time)` for bisect savings math (returns base + delivery + transmission, matching the v4.6.8 canonical rate shape) and `EnergyCoordinator.current_effective_rate` for "rate right now" sanity reads. Reduces the bisect-savings math drift between EC and AC. **The v3 draft proposed `EnergyCoordinator.get_current_rate_for_period(period: str) -> float` — that signature does NOT exist; see Open Q#7 (resolved) for the actual API.**

3. **v4.6.7's `anomaly_log` NOT NULL relaxation reshapes the anomaly emit pattern.** Five metric columns are now nullable. The interrupt-at-start path historically had a "metrics not applicable" problem (no `setup_duration`, no `loop_duration`); v3 takes advantage of this by emitting interrupt-specific events with the appliance-relevant subset populated only.

What carries forward unchanged from v2:
- The 12 design principles (with one wording tweak on Principle 9 to swap "Dashboard v5.0+" for "URA PWA v6.0+").
- ApplianceProvider ABC v2 (3 new methods, 2 new capability flags).
- Strictness config schema (per-appliance options-flow shape).
- State Machine v2 with INTERRUPTED state.
- Bisect decision pseudocode.
- Multi-vector power architecture.
- The 12 deliverables D1-D12 (refined acceptance criteria where the PWA contract bites).

---

## Tier 2-DB Decision

**Verdict: YES — Tier 2-DB applies. Three parallel reviewers with different framings.**

Triggers met (per `CLAUDE.md` Tier 2-DB criteria):

1. **Touches `database.py` DAO definitions.** D4 adds `save_appliance_sm_row`, `load_pending_sm_rows`, `delete_appliance_sm_row`, `cleanup_appliance_sm_rows` plus a new `appliance_state_machine` table.
2. **Migrates ≥3 callers to a new DAO.** D2 (write transitions), D5 (reconciliation reads), D6 (failure-mode writes), D4's restore path, D10 sensor populators — five+ sites.
3. **Changes payload shape of dispatched events.** `SIGNAL_APPLIANCE_INTERRUPTED` carries `original_command_payload`; `SIGNAL_APPLIANCE_RESUMED` carries `deferred_until`. Both are new persisted-event shapes downstream consumers (NM, anomaly_log) will gate on.
4. **Adds behavioral test infra against real schemas.** D4 fixtures MUST extract the `appliance_state_machine` DDL from production source (Bug Class #39 guard).
5. **Followed by future schema work.** v4.8.0 Generic Power Sensor provider writes into the same SM table — Tier 2-DB now prevents a re-migration later.

**Review framings (run in parallel, different blind spots):**
- **Review A — Data integrity + DB architecture preservation.** No regression in existing tables (`anomaly_log`, `energy_state`, `routine_*`). Index coverage for the two new indexes. Write queue unchanged. `cleanup_appliance_sm_rows` batched + budgeted (Bug #25, #27, #29). Schema migration idempotent (single-user install — `IF NOT EXISTS` is defensive, not migration scaffolding).
- **Review B — Migration correctness + signal chain integrity.** Every SM transition produces equivalent rows AND fires the correct dispatch. INTERRUPTED → SCHEDULING fires `SIGNAL_APPLIANCE_RESUMED` exactly once. No double-emit. Field-by-field payload-shape comparison vs spec. Observation-mode gate at every dispatch (Bug #23).
- **Review C — New surfaces + test fixture authority + PWA contract.** D10's sensor/switch/select/button slate round-trips through options-flow + RestoreEntity. D1 new ABC methods exercised by tests that drive provider impls. Test fixtures extract schema from production DDL (Bug #39). **NEW for v3:** Every D10 sensor's `extra_state_attributes` matches the `UraSensorReadout` contract — no nested objects deeper than the PWA's `useUraSensorAttrs<T>` callers expect; no "unknown" / "" sentinels for numeric attrs (PWA renders em-dash on null, but parses "" / "unknown" as unavailable — coordinator must emit `None` for absent values, not empty strings).

**Pre-deploy snapshot:** Capture baseline row counts in `anomaly_log` grouped by `(coordinator, severity, type)`. `appliance_state_machine` starts at 0 rows. Post-deploy ±25% comparison applies to `anomaly_log`.

**Review D (live validation, post-restart):** Within 1 hour, at least one row in `appliance_state_machine` with non-NULL `state`, `entity_id`, `created_at`. Sentinels-only = payload broken (v4.6.1.1 / v4.6.3 precedent).

---

## Updated Design Principles (12)

Carried verbatim from v2.0 except where noted.

1. **Defer, don't interrupt — with the manual-start caveat.** (unchanged)
2. **Provider plugin pattern.** (unchanged)
3. **Entity_id source of truth.** (unchanged)
4. **Restart-survivable.** (unchanged)
5. **Sprinklers are different.** (unchanged)
6. **Fail-safe on missing inputs.** (unchanged)
7. **Strictness configurable per appliance.** (unchanged)
8. **Power monitoring is multi-vector.** (unchanged)
9. **(MODIFIED in v3)** **Observability + control: config-flow first, device-page mirror for runtime, PWA-consumable shape.** Initial config in options-flow; critical runtime knobs as switches/selects/buttons on the URA Appliance Coordinator device page. **The URA PWA v6.0+ consumes these surfaces via `useUraSensorState` / `useUraSensorInt` / `useUraSensorFloat` / `useUraSensorAttrs<T>` hooks (see `~/Code/ura-dashboard-pwa/src/data/useUraSensor.ts`). All sensor states MUST be parseable per those hooks' contracts: numeric sensors emit numeric-stringifiable values or `unavailable`, never `"—"` or `"N/A"`; `extra_state_attributes` is a flat dict (or shallow nested) keyed by stable strings.**
10. **Anomaly pattern: hardened v4.6.x framework only.** (unchanged) **v3 addendum:** v4.6.7's `anomaly_log` NOT NULL relaxation means the interrupt path can write partial metric rows — populate `appliance_id`, `state_at_event`, `reason`; leave `setup_duration` / `loop_duration` NULL (no fake zeros).
11. **Bisect math is symmetric in the TOU helper.** (unchanged)
12. **Cycle length is sensor-first, constant-fallback, never integration-best-guess.** (unchanged)

(For full prose see v2.0 §"Updated Design Principles (12)" — not re-stated here to keep v3 lean.)

---

## ApplianceProvider ABC v2 — carried from v2.0

No changes from v2.0. See v2.0 §"ApplianceProvider ABC v2 — new methods + capability flags" for:
- `ApplianceCapabilities` with `supports_cancel`, `interruptible_at_start`, `cycle_length_sensor_pattern`
- New abstract methods: `cancel_started_cycle`, `get_cycle_length`, `get_power_draw_w`
- `ProviderResult.payload: dict | None` field

LGThinQProvider: `supports_cancel=True`, `interruptible_at_start=True` (washers / washtowers / dishwashers).
RainbirdProvider: `supports_cancel=False`, `interruptible_at_start=False`.

---

## Strictness Config Schema, State Machine, Bisect Pseudocode

All carried verbatim from v2.0:
- Strictness schema under `cm_entry.options["appliance_scheduler"]["appliances"][entity_id]` (10 keys).
- INTERRUPTED state in the SM, with `original_command_payload`, `interrupted_at`, `reason` fields.
- `evaluate_manual_start()` pseudocode with bisect logic.
- PowerSignalAggregator with 30s freshness budget + priority rule.

Refer to v2.0 §§"Strictness Config Schema", "TOU Bisect Decision Pseudocode (Principle 11)", "Power Monitoring Multi-Vector Architecture", "State Machine v2 (with INTERRUPTED state)". No textual changes in v3.

---

## Deliverables (12) — Acceptance Criteria

Per `CLAUDE.md` "Planning Docs — Acceptance Criteria Required", each D has Verify / Sensor / Test / Live lines. Bug-class prevention listed inline. Where v3 changes acceptance criteria vs v2, the change is marked **(v3)**.

### D1: ApplianceProvider ABC v2 + LGThinQProvider with cancel + cycle-length + power
**What:** v2.0 D1 verbatim. New ABC methods + capability flags; LGThinQ implements all three; verify service surface via `hass.services.async_services()`.
**Files:** `domain_coordinators/appliance_providers/{base,lg_thinq,_cycle_defaults}.py`.
**Bug class prevention:** #22 (StrEnum), #29 (every status branch has populator), #37 (ABC enforces new contract).
**Acceptance Criteria:**
- **Verify:** All 6 LG appliances enumerate; `interruptible_at_start=True` for each.
- **Verify:** `cancel_started_cycle(entity_id, reason)` returns `ProviderResult(ok=True, payload={...})`; idempotent second call returns `ok=True, no_op=True`.
- **Verify:** `get_cycle_length(washer)` returns a positive int when remaining-time sensor present, else `None`.
- **Sensor:** `sensor.ura_appliance_coordinator_provider_status` exposes per-provider availability + capability flags via `extra_state_attributes.providers: list[{id, present, capabilities}]`.
- **Test:** `test_lg_thinq_cancel_started_cycle_returns_payload`, `test_lg_thinq_cycle_length_sensor_path`, `test_lg_thinq_cycle_length_no_sensor_returns_none`, `test_provider_abc_enforces_new_methods`.
- **Live:** Manual START on a washer during peak; URA issues cancel within 30s; `sensor.ura_appliance_coordinator_last_blocked_start` updates within one tick.

### D2: Appliance Coordinator core with strictness flow + interrupt path
**What:** v2.0 D2 verbatim. `evaluate_manual_start()` + INTERRUPTED handling + `_refresh_config()` per-appliance merge + `PowerSignalAggregator` integration.
**Files:** `domain_coordinators/appliances.py`, `domain_coordinators/signals.py`.
**Bug class prevention:** #1, #2, #14, #19, #23, #37.
**Acceptance Criteria:**
- **Verify:** Coordinator registers in CM with priority 25; survives `async_stop`/`async_start`.
- **Verify:** Manual start during peak with `interrupt_manual_start=True` fires `SIGNAL_APPLIANCE_INTERRUPTED` exactly once; SM reaches INTERRUPTED → SCHEDULING within one tick.
- **Verify:** `interrupt_manual_start=False` → manual start in peak is ignored, no cancel issued.
- **Sensor:** `sensor.ura_appliance_coordinator_pending_deferrals` (int state) + `extra_state_attributes.deferrals: list[{entity_id, target_run_time_iso, reason, state}]` — **(v3)** flat list-of-flat-dicts only; the PWA's `useUraSensorAttrs<T>` will type `T = { deferrals: Deferral[] }`.
- **Test:** `test_evaluate_manual_start_allows_in_off_peak`, `test_evaluate_manual_start_interrupts_in_peak_when_bisect_set`, `test_evaluate_manual_start_respects_tolerate_mid_peak`, `test_interrupted_state_persists_payload`, `test_pending_tasks_cancelled_on_teardown`.
- **Live:** Press start during peak with `on_bisect=prefer_off_peak`; observe interrupt + arming for next off-peak boundary; PWA `Appliance` tab (when ported) reflects within one HA WebSocket tick.

### D3: TOU `get_minutes_until_period` bidirectional helper
**What:** v2.0 D3 verbatim. Extends `energy_tou.py` after line 235.
**Files:** `domain_coordinators/energy_tou.py`.
**Bug class prevention:** #11 (timezone), #22 (composite period validated).
**Acceptance Criteria:**
- **Verify:** At 15:30 with peak 16:00-21:00, `get_minutes_until_period("peak") == 30`; `get_minutes_until_period("off_peak") == 330`.
- **Verify:** During off_peak, `get_minutes_until_period("off_peak") == 0`.
- **Verify:** `get_minutes_until_period("off_or_mid_peak")` during peak returns minutes to earlier of mid_peak/off_peak transition.
- **Sensor:** `sensor.ura_energy_coordinator_tou_status` gains `extra_state_attributes.minutes_until_off_peak` (int) and `.minutes_until_peak` (int) — **(v3)** both consumable by `useUraSensorInt` if the PWA later wants direct numeric reads.
- **Test:** `test_minutes_until_peak_at_30_minutes`, `test_minutes_until_composite_off_or_mid_peak`, `test_minutes_until_period_dst_transition`, `test_minutes_until_period_invalid_target_raises`.
- **Live:** TOU status sensor attrs match hand calculation against PEC schedule.

### D4: Persistence — deferrals AND stalled starts
**What:** v2.0 D4 verbatim. `appliance_state_machine` table; four DAO methods; restore-on-setup.
**Files:** `database.py`, `domain_coordinators/appliances.py`.
**Bug class prevention:** #10, #21 (parse_datetime), #25 (batched DELETE), #27 (nightly maintenance), #29 (budget-aware), #39 (fixture from production DDL — Tier 2-DB Review C).
**Acceptance Criteria:**
- **Verify:** Manual start during peak → INTERRUPTED row persisted with `original_command_payload` non-NULL. Kill HA, restart 5 min later, row restored.
- **Verify:** Restart after target_time long-past → row marked EXPIRED, no spurious service call.
- **Sensor:** `sensor.ura_appliance_coordinator_restored_deferrals` (int state) + `extra_state_attributes.restored_by_state: {INTERRUPTED: int, ARMED: int, SCHEDULING: int}` — **(v3)** flat keyed dict, PWA-parseable.
- **Test:** `test_persist_interrupted_with_payload_and_restore`, `test_persist_armed_and_restore`, `test_expired_dropped`, `test_cleanup_appliance_sm_rows_batched`, `test_cleanup_registered_in_nightly_maintenance` (lint), `test_schema_extracted_from_production_ddl` (Bug #39 — Tier 2-DB requirement).
- **Live:** Stall a manual start; verify DB row via `ura-sqlite` MCP within seconds; restart HA; verify resume; **(v3)** verify `appliance_state_machine` row count > 0 within 1h of any deploy (Review D check).

### D5: Reload resilience + reconciliation
**What:** v2.0 D5 verbatim. 5-min reconciliation walk also covers INTERRUPTED rows.
**Files:** `domain_coordinators/appliances.py`.
**Bug class prevention:** #20, #22, #38 (`async_listen` unsubs tracked).
**Acceptance Criteria:**
- **Verify:** Disable + re-enable LG ThinQ; INTERRUPTED/ARMED rows untouched; no double service call after reload.
- **Verify:** Reload Appliance Coordinator entry; in-memory SM rebuilt from DB; identical state.
- **Sensor:** `sensor.ura_appliance_coordinator_reconciliation_count` (int state) + `extra_state_attributes.last_reconciliation_summary: {INTERRUPTED: int, ARMED: int, SCHEDULING: int, RUNNING: int, COMPLETE: int}`.
- **Test:** `test_no_double_service_call_on_lg_reload`, `test_state_listener_uses_entity_id_not_object`, `test_reconciliation_transitions_interrupted_to_scheduling_at_period_flip`.
- **Live:** Reload LG ThinQ during ARMED; verify zero extra service calls in trace.

### D6: Failure-mode SM completion + observation mode + signals
**What:** v2.0 D6 verbatim. Wire observation-mode gate at every dispatch (Bug #23). Dispatch new `SIGNAL_APPLIANCE_INTERRUPTED` + `SIGNAL_APPLIANCE_RESUMED`.
**Files:** `domain_coordinators/appliances.py`, `domain_coordinators/signals.py`.
**Bug class prevention:** #23, #28 (async `add_update_listener`), #24 (lambda scope).
**Acceptance Criteria:**
- **Verify:** Observation mode ON → `evaluate_manual_start` runs but never calls `cancel_started_cycle`; logs intent only.
- **Verify:** Provider `cancel` returns `ok=False, reason='not_interruptible'` → SM goes to RUNNING; `sensor.ura_appliance_coordinator_interrupt_skipped_today` increments.
- **Sensor:** `sensor.ura_appliance_coordinator_state_machine_breakdown` (state = total non-terminal count) + `extra_state_attributes` keyed `{evaluating, scheduling, interrupted, armed, expecting_run, running, complete, anomaly, dropped, cancelled}` — all int.
- **Test:** `test_observation_mode_blocks_interrupt_at_dispatch`, `test_cancel_failure_falls_through_to_running`, `test_signal_interrupted_payload_shape`.
- **Live:** Toggle observation mode ON; press START during peak; zero service calls; log entry only.

### D7: RainbirdProvider + forecast-aware skip
**What:** v2.0 D7 verbatim. Rain delay translation, weather threshold, no active-cycle interrupt.
**Bug class prevention:** #8 (forecast dict guards), #11 (UTC→local), #26 (forecast cache TTL via `time.monotonic()`).
**Acceptance Criteria:**
- **Verify:** Mock 80% rain probability tomorrow → coordinator issues `set_rain_delay(1)` on next decision tick.
- **Verify:** Forecast < threshold → no service call.
- **Verify:** Active sprinkler cycle NOT interrupted by skip decision.
- **Sensor:** `sensor.ura_appliance_coordinator_sprinkler_skips_today` (int) + `extra_state_attributes.last_skip: {timestamp_iso, threshold_met, forecast_pct, forecast_precip_in}`.
- **Test:** `test_skip_when_high_rain_probability`, `test_no_skip_when_low_probability`, `test_no_skip_when_forecast_stale`, `test_active_cycle_not_interrupted`, `test_forecast_response_dict_guards`.
- **Live:** Wait for next forecasted-rain day; verify rain-delay set; zero zone interruptions mid-cycle.

### D8: Rainbird master kill-switch
**What:** v2.0 D8 verbatim. `switch.ura_appliance_coordinator_rainbird_enabled` as discrete observable surface.
**Files:** `domain_coordinators/appliances.py`, `switch.py`.
**Bug class prevention:** #35 (switch wired to refresh signal), #32 (no orphan form field).
**Acceptance Criteria:**
- **Verify:** Toggling `switch.ura_appliance_coordinator_rainbird_enabled = OFF` halts all subsequent Rainbird service calls within one decision tick.
- **Verify:** Toggling ON resumes forecast evaluation on next 30-min decision tick.
- **Sensor:** `sensor.ura_appliance_coordinator_rainbird_status` (string state: `enabled|disabled|no_provider`).
- **Test:** `test_rainbird_kill_switch_halts_service_calls`, `test_rainbird_kill_switch_restore`, `test_rainbird_status_sensor_populator`.
- **Live:** Flip OFF; manual trigger evaluation; confirm zero `rainbird.*` service calls in trace.

### D9: GenericPowerSensorProvider (deferred to v4.8.0 ship)
**What:** v2.0 D9 verbatim. Read-only provider over `PowerSignalAggregator`.
**Acceptance Criteria:** v2.0 D9 verbatim.

### D10: Observability + Dashboard hooks (PWA-grounded in v3)
**What:** v2.0 D10 entity slate (sensors, switches, selects, buttons) **(v3) re-grounded against the PWA hook contract.** Every entity below is annotated with the PWA hook a caller would use; `extra_state_attributes` shapes are constrained to PWA-parseable shapes.

**Files:** `sensor.py`, `switch.py`, `select.py`, `button.py`.

**Sensors (PWA hook in parens):**
- `sensor.ura_appliance_coordinator_pending_deferrals` — int (`useUraSensorInt`); attrs `{deferrals: Deferral[]}` (`useUraSensorAttrs<{deferrals: Deferral[]}>`)
- `sensor.ura_appliance_coordinator_last_blocked_start` — string `"<appliance>: <reason>"` (`useUraSensorState`); attrs `{timestamp_iso, resumed_at_iso, entity_id, reason}`
- `sensor.ura_appliance_coordinator_deferrals_today` — int (`useUraSensorInt`)
- `sensor.ura_appliance_coordinator_savings_today_kwh` — float (`useUraSensorFloat`)
- `sensor.ura_appliance_coordinator_savings_today_dollars` — float (`useUraSensorFloat`); **(v3)** uses EC v4.6.8 canonical rate — `TOURateEngine.get_effective_import_rate(now=projected_dt)` for arbitrary-instant lookups; never local rate constants
- `sensor.ura_appliance_coordinator_anomaly_status` — string `green|orange|red` (`useUraSensorState`); attrs `{drop_rate, drops_24h, last_drop_iso}`
- `sensor.ura_appliance_coordinator_state_machine_breakdown` — int total (`useUraSensorInt`); attrs flat dict keyed by SM state name
- `sensor.ura_appliance_coordinator_rainbird_status` — string (`useUraSensorState`)
- `sensor.ura_appliance_coordinator_provider_status` — string (overall) (`useUraSensorState`); attrs `{providers: ProviderStatus[]}`
- `sensor.ura_appliance_coordinator_sprinkler_skips_today` — int (`useUraSensorInt`)
- `sensor.ura_appliance_coordinator_interrupt_skipped_today` — int (`useUraSensorInt`)
- `sensor.ura_appliance_coordinator_power_freshness_penalty_events_today` — int (`useUraSensorInt`)
- `sensor.ura_appliance_coordinator_restored_deferrals` — int (`useUraSensorInt`); attrs `restored_by_state`
- `sensor.ura_appliance_coordinator_reconciliation_count` — int (`useUraSensorInt`); attrs `last_reconciliation_summary`

**Switches:**
- `switch.ura_appliance_coordinator_scheduling_enabled` (global)
- `switch.ura_appliance_<id>_scheduling_enabled` (per appliance)
- `switch.ura_appliance_<id>_interrupt_manual_start` (per appliance)
- `switch.ura_appliance_coordinator_rainbird_enabled` (D8)

**Selects (named buckets per `feedback_configurability_clarity.md`):**
- `select.ura_appliance_<id>_on_bisect` — `stop | start | prefer_off_peak`
- `select.ura_appliance_<id>_max_delay_bucket` — `15m | 1h | 4h | 8h | overnight`

**Buttons:**
- `button.ura_appliance_coordinator_cancel_pending_deferrals`
- `button.ura_appliance_<id>_resume_now`

**PWA contract guards (v3):**
- No sensor emits `"—"`, `"N/A"`, `"None"`, `"null"` as a state value. Unavailable values flow as HA `STATE_UNAVAILABLE` so `useUraSensorState.unavailable` is true.
- All `extra_state_attributes` are JSON-serializable, no datetime objects (use ISO 8601 strings), no Decimal (use float).
- Attributes are flat dicts or shallowly-nested lists-of-flat-dicts. No nested-dict-of-nested-dict shapes.
- Sensor `unique_id` follows existing URA naming (`appliance_coordinator_<name>` / `appliance_<entity_slug>_<name>`).

**Bug class prevention:** #29 (every sensor has populator path tested), #32 (every form field has runtime reader), #35 (buttons wired to refresh signal), #36 (per-appliance dedup analogue).

**Acceptance Criteria:**
- **Verify:** All entities listed appear on `URA: Appliance Coordinator` device page after setup with 6 LG appliances.
- **Verify:** `select.ura_appliance_<id>_on_bisect` change persists to options AND picked up by next `_refresh_config()` without restart (Bug #14).
- **Verify:** `button.ura_appliance_<id>_resume_now` on an INTERRUPTED entry triggers immediate SCHEDULING transition.
- **Verify (v3):** Every sensor passes a `useUraSensor*` parser-shape smoke test — int sensors parse to non-null int, float to non-null float, string to non-empty string when populated. Test fixture mirrors `useUraSensorState` semantics.
- **Sensor:** `..._anomaly_status` reports `green` when 0 drops in 24h, `orange` if drop_rate > 0, `red` if drop_rate > 20%.
- **Test:** AST-level smoke test enumerating expected `unique_id`s; behavioral `test_resume_now_button_force_schedules`; populator coverage per Bug #29; **(v3)** `test_pwa_attribute_shape_flatness` (asserts no nested-dict-of-nested-dict).
- **Live:** Open PWA `Appliance` tab (once ported in PWA repo); all sensors render correctly; toggling a switch reflects in PWA within one HA WebSocket tick.

### D11: PowerSignalAggregator + multi-vector discipline
**What:** v2.0 D11 verbatim.
**Files:** `domain_coordinators/appliance_providers/_power_signal.py`.
**Bug class prevention:** #11 (timestamp arithmetic), #26 (5s in-tick cache).
**Acceptance Criteria:** v2.0 D11 verbatim.

### D12: Cycle-length source-of-truth
**What:** v2.0 D12 verbatim.
**Files:** `domain_coordinators/appliance_providers/_cycle_defaults.py`.
**Bug class prevention:** #14, #22.
**Acceptance Criteria:** v2.0 D12 verbatim.

---

## Dashboard Hooks (URA PWA v6.0+) — explicit contract

**Repo:** `~/Code/ura-dashboard-pwa/`. Hook layer: `src/data/useUraSensor.ts`. Coordinator MUST conform to this contract — the PWA is in a separate repo and updates ship independently.

**Hook contract recap (from `useUraSensor.ts`):**
- `useUraSensorState(entityId) -> { state, loading, unavailable, attributes, last_updated }`
  - `state`: raw string from HA, or `null` if entity missing
  - `unavailable`: true when state is `""`, `"unavailable"`, or `"unknown"`
- `useUraSensorInt(entityId) -> { value: number | null, loading }`: `Number.parseInt(state, 10)`, returns `null` on NaN/unavailable
- `useUraSensorFloat(entityId) -> { value: number | null, loading }`: `Number.parseFloat(state)`
- `useUraSensorAttrs<T>(entityId) -> { attrs: T | null, loading, unavailable }`: UNCHECKED cast — coordinator must guarantee shape

**Sensors the Appliance Coordinator exposes for the PWA (consolidated from D10):**

| Entity ID | State Type | PWA Hook | Key Attributes |
|---|---|---|---|
| `sensor.ura_appliance_coordinator_pending_deferrals` | int | `useUraSensorInt` | `deferrals: Deferral[]` |
| `sensor.ura_appliance_coordinator_last_blocked_start` | string | `useUraSensorState` | `timestamp_iso, resumed_at_iso, entity_id, reason` |
| `sensor.ura_appliance_coordinator_deferrals_today` | int | `useUraSensorInt` | — |
| `sensor.ura_appliance_coordinator_savings_today_kwh` | float | `useUraSensorFloat` | — |
| `sensor.ura_appliance_coordinator_savings_today_dollars` | float | `useUraSensorFloat` | `rate_delta_used` |
| `sensor.ura_appliance_coordinator_anomaly_status` | string | `useUraSensorState` | `drop_rate, drops_24h, last_drop_iso` |
| `sensor.ura_appliance_coordinator_state_machine_breakdown` | int | `useUraSensorInt` | `{state_name: int, ...}` |
| `sensor.ura_appliance_coordinator_rainbird_status` | string | `useUraSensorState` | `last_skip_iso` |
| `sensor.ura_appliance_coordinator_provider_status` | string | `useUraSensorState` | `providers: ProviderStatus[]` |
| `sensor.ura_appliance_coordinator_sprinkler_skips_today` | int | `useUraSensorInt` | `last_skip` (flat dict) |
| `sensor.ura_appliance_coordinator_interrupt_skipped_today` | int | `useUraSensorInt` | — |
| `sensor.ura_appliance_coordinator_power_freshness_penalty_events_today` | int | `useUraSensorInt` | — |
| `sensor.ura_appliance_coordinator_restored_deferrals` | int | `useUraSensorInt` | `restored_by_state` (flat) |
| `sensor.ura_appliance_coordinator_reconciliation_count` | int | `useUraSensorInt` | `last_reconciliation_summary` (flat) |

**Refresh semantics:** All sensors update via the standard HA state-change event; the PWA receives them via WebSocket through the Zustand store. The coordinator MUST call `async_write_ha_state()` on its sensor entities at every SM transition AND at every daily-counter rollover (`_maybe_reset_daily_counters` pattern). No bespoke push services — the PWA is pure subscriber.

**Type definitions the PWA tab authors will inline (informational, lives in PWA repo, not URA):**
```ts
type Deferral = { entity_id: string; target_run_time_iso: string; reason: string; state: string };
type ProviderStatus = { id: string; present: boolean; capabilities: Record<string, boolean | string | number> };
```

**Shape stability commitment:** Renaming any attribute key listed above is a BREAKING change for the PWA. Adding new attributes is non-breaking. Removing an attribute is breaking. Future cycles touching this coordinator must respect the table above as a published contract.

---

## Implementation Order + Ship Plan

Carried from v2.0 — unchanged:

```
D3, D11, D12 (helpers, parallelizable)
  -> D1 (provider ABC + LGThinQ; needs D11 + D12)
  -> D2 (coordinator core; needs D1 + D3)
  -> D4 (persistence; needs D2)
  -> D5, D6, D10 (parallel after D2 + D4)
  -> D7, D8 (parallel after D6)
  -> D9 (parallel after D6; needs D11)
```

**Ship plan:**
- **v4.7.0** — D3, D11, D12, D1, D2, D4, D6, D10 (LG cost-deferral + interrupt + PWA observability)
- **v4.7.1** — D5 (reload resilience hardening)
- **v4.7.2** — D7 + D8 (sprinkler skip + kill switch)
- **v4.8.0** — D9 (generic power sensor provider)

---

## Risk Register (carries v2.0 + 3 v3-additions)

v2.0 risks unchanged. **New v3 risks:**

| Risk | Severity | Mitigation |
|---|---|---|
| **(v3) PWA contract drift** — D10 sensor attribute shape changes silently, PWA tabs break | HIGH | Shape-table above is the contract; Review C runs the `test_pwa_attribute_shape_flatness` regression; any future shape change requires the PWA repo's `useUraSensorAttrs<T>` type to update first (manual coordination, single user) |
| **(v3) Savings drift from EC** — `savings_today_dollars` recomputes rates locally, drifts from EC v4.6.8 canonical surface | MEDIUM | D10 acceptance explicitly: consume `TOURateEngine.get_effective_import_rate(now=projected_dt)` (verified live 2026-05-25) for arbitrary-instant rates; `EnergyCoordinator.current_effective_rate` for "now"; NEVER local rate constants |
| **(v3) anomaly_log partial-row regression** — v4.6.7 relaxed NOT NULL but downstream readers may still expect populated metric columns | MEDIUM | Review A spot-check: confirm any analytics queries against `anomaly_log` handle NULL metric columns. Interrupt-path events emit `appliance_id`, `state_at_event`, `reason` only |

Carried v2.0 risks (in v3 verbatim):
- False-positive interrupt during ramp-up (HIGH)
- User confusion when device suddenly stops (HIGH)
- Provider rejects `cancel_started_cycle` mid-flight (MEDIUM)
- INTERRUPTED payload too large (MEDIUM)
- Race: manual start fires while ARM in flight (MEDIUM)
- Cycle-length sensor stale or wrong (MEDIUM)
- Multi-vector disagreement ignored (LOW)
- Rainbird kill-switch toggled mid-evaluation (LOW)
- Schema migration collision (LOW — clean install per `feedback_single_user_no_backcompat.md`)
- Test fixtures hand-copy DDL (MEDIUM)

---

## Bug-class Prevention Checklist (focused subset)

The cycle touches these QUALITY_CONTEXT.md bug classes most directly. Each has a prevention measure baked into a specific deliverable:

| Bug Class | Description | Prevention | Deliverable |
|---|---|---|---|
| #1 | Coordinator lifecycle confusion (`async_added_to_hass` on coordinators) | Use `async_config_entry_first_refresh` / `async_setup` | D2 |
| #2 | Config storage pattern (entry.data vs entry.options) | `config = {**entry.data, **entry.options}` in `_refresh_config()` | D2 |
| #8 | Forecast response dict guards | `isinstance(response, dict)` + `isinstance(forecasts, list)` | D7 |
| #10 | Restart resilience | Persisted SM rows restored on `async_setup` | D4 |
| #11 | Timezone/timestamp mixing | `dt_util.now()` only; no naive datetimes | D3, D7, D11 |
| #14 | Config staleness — restart-only configurability | `_refresh_config()` at top of every entry point | D2, D8, D10 |
| #19 | Untracked background tasks | `_pending_tasks` set; add/discard on every `async_create_task` | D2 |
| #20 | Concurrent reload race / `async_update_entry` cross-entry | No cross-entry `async_update_entry` from this coordinator | D5 |
| #21 | Datetime parsing — `fromisoformat` vs `parse_datetime` | All DB-restored timestamps via `dt_util.parse_datetime` | D4 |
| #22 | Enum mismatch (StrEnum vs string compare) | `ApplianceStatus`, `RemoteStartState`, TOU period are StrEnum; comparisons via `.value` | D1, D3, D5 |
| #23 | Observation-mode gating at dispatch | Gate at every `async_dispatcher_send` site | D2, D6 |
| #24 | Lambda scope at module/init time | Module-level imports only | D6 |
| #25 | Unbatched DELETE | `WHERE rowid IN (... LIMIT 1000)` batched | D4 |
| #26 | DB/service cache TTL via `time.monotonic()` | Forecast cache 30 min; power-signal in-tick cache 5s | D7, D11 |
| #27 | Orphaned cleanup not scheduled | `cleanup_appliance_sm_rows` registered in nightly maintenance ops list | D4 |
| #28 | Sync `add_update_listener` | All `add_update_listener` registrations `async def` | D6 |
| #29 | Sensor populator missing | Every `sensor.ura_appliance_coordinator_*` covered by populator test | D10 |
| #32 | Orphan form field — config option with no runtime reader | Every option in strictness schema has a `_refresh_config()` reader | D10 |
| #35 | Switch entity not wired to refresh signal | Switches dispatch refresh signal on toggle | D8, D10 |
| #37 | API contract (stable signal payload shape) | `SIGNAL_APPLIANCE_*` payload schemas frozen; Review B field-by-field check | D2, D6 |
| #38 | `async_listen` unsubscribes tracked | All listener handles in `_unsub_listeners` | D5 |
| #39 | Test fixtures hand-copy DDL → drift | Fixtures extract schema from production source — Tier 2-DB Review C requirement | D4 |

---

## Open Questions (Flag for Implementation)

Carried from v2.0:
1. Exact LG ThinQ service surface (`set_delay_start` vs `wash_set_delay_start`) — verify in HA service registry at config-flow time.
2. Rainbird integration variant (official vs HACS) — verify before D7.
3. CM observation mode flag key — mirror HVAC at `domain_coordinators/hvac.py`.
4. Cycle kWh defaults for savings calc — confirm in D2 config-flow.
5. "Materially started" threshold — default: any power draw > 200W for ≥60s = materially started.
6. Resume payload schema across LG firmware versions — capture as opaque `dict[str, Any]`.

**New for v3:**
7. ~~**EC v4.6.8 rate API name.**~~ **RESOLVED 2026-05-25** by live source verification (`energy.py:3552` + `energy_tou.py:178/194`). The v3 draft's provisional `EnergyCoordinator.get_current_rate_for_period(period: str) -> float` does NOT exist. Actual API:
   - `EnergyCoordinator.current_effective_rate` — property, no args, returns the current effective rate (`float`, base + delivery + transmission) for "now". Delegates to `self._billing.current_effective_rate`.
   - `TOURateEngine.get_current_rate(now=None)` — base power charge only (`$/kWh`), at arbitrary instant. Period resolution is internal.
   - `TOURateEngine.get_effective_import_rate(now=None)` — base + delivery + transmission, at arbitrary instant. **This is the bisect-savings math input** (matches the v4.6.8 canonical cost-vocabulary).
   - `TOURateEngine.get_export_rate(now=None)` — export credit at arbitrary instant.

   D10 `savings_today_dollars` consumes `get_effective_import_rate(now=projected_run_time)` for both "what it would cost now" and "what it would cost deferred" arms of the bisect. `current_effective_rate` is reserved for sanity reads.
8. **PWA tab port timing for Appliance.** The PWA repo is separate; whether the Appliance tab port lands in the same calendar window as URA v4.7.0 is a coordination question. The URA side has zero dependency on the tab existing — sensors must be correct in either case. Flag only so the user can sequence PWA port work.
9. **`anomaly_log` partial-row downstream readers.** v4.6.7 relaxed NOT NULL on 5 metric columns. Does any existing dashboard/analytics query against `anomaly_log` assume those columns non-NULL? Audit needed at D6 build (Review A scope).

---

## What's NOT in v3 (scope guards)

Unchanged from v2.0:
- Mid-cycle interrupt (running cycle pause). Only manual-start pre-material interrupt is in.
- Per-zone sprinkler rain skip (would need soil sensors).
- Demand-response (utility-driven event signaling).
- Per-appliance ML cycle-length prediction.
- Pause-and-resume across TOU boundaries.
- Microwave / oven scheduling (no remote start, immediate-use).
- Gas dryer active control (D9 covers it informationally).

**Explicitly NOT in v3 (single-user install per `feedback_single_user_no_backcompat.md`):**
- Schema migration scaffolding beyond `CREATE TABLE IF NOT EXISTS`.
- Compatibility shims for old `appliance_deferrals` table (never shipped).
- Mode-toggle scaffolding for "old SM vs new SM" — there is no old.

---

## Live-Validation Checklist (post-deploy)

| # | Check | Tool |
|---|---|---|
| 1 | All 6 LG appliances enumerated in config-flow | UI |
| 2 | Press START on a washer in peak with `interrupt_manual_start=ON` → washer stops within 30s | Manual + log |
| 3 | INTERRUPTED row in `appliance_state_machine` with `original_command_payload` non-NULL | `ura-sqlite` MCP |
| 4 | At peak end, washer auto-resumes via `set_delay_start` | HA log + appliance UI |
| 5 | `sensor.ura_appliance_coordinator_last_blocked_start` non-empty + attrs flat | HA UI |
| 6 | `sensor.ura_appliance_coordinator_savings_today_dollars` matches hand calc within 10%; uses `TOURateEngine.get_effective_import_rate(now=...)` (no local rate constants in `appliances.py`) | manual math + log + AST check |
| 7 | Toggle `switch.ura_appliance_coordinator_scheduling_enabled = OFF` → no new ARMs for 1h | HA log |
| 8 | Toggle `switch.ura_appliance_coordinator_rainbird_enabled = OFF` → no `rainbird.*` calls | HA log |
| 9 | After HA restart, INTERRUPTED rows restored within 60s | log + DB |
| 10 | Zero stale-task warnings in HA log within first hour post-restart | log |
| 11 | `anomaly_log` row counts ±25% vs pre-deploy baseline by (coordinator, severity, type) | `ura-sqlite` MCP |
| 12 | **(v3)** All D10 sensors parse correctly via `useUraSensor*` hook contract — int sensors return non-null numbers, no `"—"` / `"N/A"` strings | PWA load + browser devtools, OR Python parser-shape smoke test |
| 13 | **(v3)** `appliance_state_machine` row count > 0 within 1h of deploy (Review D — payload-shape integrity check) | `ura-sqlite` MCP |

---

## References (verified)

From v2.0 (unchanged):
- `domain_coordinators/energy_tou.py:37` — `_VALID_PERIODS`
- `domain_coordinators/energy_tou.py:199` — `get_next_transition()`
- `domain_coordinators/hvac.py:194` — `_pending_tasks` pattern
- `domain_coordinators/coordinator_diagnostics.py:704` — `AnomalyDetector`
- `domain_coordinators/coordinator_diagnostics.py:978` — `store_event`
- `domain_coordinators/coordinator_diagnostics.py:1024` — `load_baselines`
- `domain_coordinators/coordinator_diagnostics.py:1104` — `save_baselines`
- `domain_coordinators/manager.py:236` — `register_coordinator`
- `domain_coordinators/base.py:164` — priority docstring
- `domain_coordinators/signals.py:12-64` — existing `SIGNAL_*` constants

**New in v3:**
- `/Users/okosisi/Code/ura-dashboard-pwa/src/data/useUraSensor.ts` — PWA hook layer; canonical contract for D10 sensor shapes
- `docs/QUALITY_CONTEXT.md` v7.2 — 31 documented bug classes

**Verified live 2026-05-25 (Open Q#7 resolution):**
- `domain_coordinators/energy.py:3552` — `EnergyCoordinator.current_effective_rate` property
- `domain_coordinators/energy_tou.py:178` — `TOURateEngine.get_current_rate(now=None)` (base only)
- `domain_coordinators/energy_tou.py:194` — `TOURateEngine.get_effective_import_rate(now=None)` (base + delivery + transmission — D10 savings sensor's input)
- `domain_coordinators/energy_tou.py:186` — `TOURateEngine.get_export_rate(now=None)`

---

**End of PLANNING_v4.7.x_APPLIANCE_COORDINATOR_v3.md.**
