# B5: URA Appliance Coordinator v2 — Interrupt-Aware Cost Deferral, Strictness Knobs & Forecast-Aware Sprinklers

**Version:** 2.0 (2026-05-19)
**Status:** Ready to build (queued as v4.7.x)
**Supersedes:** `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md` v1.1 (kept for history; cross-linked above)
**Depends on:** Energy Coordinator (v4.0.0+ TOU engine, `get_next_transition` at `domain_coordinators/energy_tou.py:199`), Coordinator Manager v3.6+ (`register_coordinator` at `domain_coordinators/manager.py:236`), URADatabase v4.6.x (write queue with batching + budgeting; anomaly_log NOT NULL-relaxed at v4.6.7)
**Effort estimate:** ~36-46h (vs v1.0's 28-36h — interrupt path + strictness + power-vector aggregation adds ~10h)
**Priority:** MEDIUM-HIGH

---

## Why v2 (and why now)

v1.0 specified a clean "defer-only" model. The 2026-05-19 user reax expanded the cycle scope:

1. **Interrupt-at-start is in-scope.** EV-charging precedent — when an energy-unconscious member presses START during peak, URA stops the device and re-schedules it. v1.0's D1-D8 had no provider method for this and no SM state for "stalled, awaiting resume."
2. **Strictness is a UX surface, not a hard-coded policy.** Per-appliance knobs (`tolerate_mid_peak`, `on_bisect`) need an options-flow schema AND device-page mirrors.
3. **Power detection is multi-vector by necessity.** Device-native power entities are not always present, not always real-time. Mains-circuit monitors fill the gap, with a 30s polling-tolerance discipline.
4. **Observability is a deliverable, not a footnote.** Dashboard v5.0+ consumes the same surfaces; the coordinator must publish them deliberately.
5. **Rainbird has a kill switch.** A separate URA-side master toggle so the homeowner can opt URA out without uninstalling.
6. **Cycle-length source-of-truth is its own decision.** Sensor-preferred, fallback-constant — needed by bisect math AND by savings estimation; deserves an explicit deliverable so neither feature owns it implicitly.

Each of these shifts the shape of D1-D8 enough that a fresh deliverable map is cheaper than patching v1.1.

---

## Updated Design Principles (12)

Principles 1-10 are inherited from v1.1 (see that doc for full prose). Two additions promote v1.1's pseudocode and savings-math decisions to first-class principles.

**1. Defer, don't interrupt — with the manual-start caveat.** (v1.1) Scheduler will not pause a running cycle. It MAY interrupt a manual start that fired in a disallowed window IF the appliance is `interruptible_at_start = True`. The interrupted command is captured as a *stalled start* and resumed via scheduling. Materially-running cycles (water drawn, oven preheated) are never interrupted.

**2. Provider plugin pattern.** (v1.1) Concrete providers in `domain_coordinators/appliance_providers/*.py`; coordinator never touches integration internals.

**3. Entity_id source of truth.** (v1.1) Hold strings, resolve fresh per call. LG ThinQ reconnects safely.

**4. Restart-survivable.** (v1.1) Deferrals AND stalled starts persisted; restored on `async_setup`.

**5. Sprinklers are different.** (v1.1) Days, not minutes. Only future cycles suppressed.

**6. Fail-safe on missing inputs.** (v1.1) No TOU → pass-through. Stale forecast → no skip. Provider down → log + drop.

**7. Strictness configurable per appliance.** (v1.1) Per-appliance options-flow schema: `tolerate_mid_peak: bool`, `on_bisect: Literal[stop, start, prefer_off_peak]`, `cycle_length_source: Literal[sensor, fallback]`. Mirrored to runtime select entities so the homeowner doesn't restart options-flow for daily tweaks.

**8. Power monitoring is multi-vector.** (v1.1) Prefer device-native; fall back to mains-circuit; 30s worst-case freshness budget. When vectors disagree → device-native if fresh; else circuit + freshness penalty.

**9. Observability + control: config-flow first, device-page mirror for runtime.** (v1.1) Initial config in options-flow; critical runtime knobs as switches/selects/buttons on the URA Appliance Coordinator device page. Dashboard v5.0+ consumes these.

**10. Anomaly pattern: hardened v4.6.x framework only.** (v1.1) `AnomalyDetector` from `domain_coordinators/coordinator_diagnostics.py:704`. `load_baselines` (line 1024) on `async_start`, `save_baselines` (line 1104) after observation, `store_event` (line 978) for dispatch. CM `setup_duration` wiring at `__init__.py` is canonical for once-per-trigger metrics.

**11. (NEW) Bisect math is symmetric in the TOU helper.** A single `get_minutes_until_period(target_period, now=None)` answers both "when does cheap arrive?" and "when does cheap end?" — so the *defer* decision and the *interrupt-at-start* decision share one helper and one period vocabulary. Avoids Bug Class #22 (enum mismatch) by sharing `_VALID_PERIODS` (at `domain_coordinators/energy_tou.py:37`).

**12. (NEW) Cycle length is sensor-first, constant-fallback, never integration-best-guess.** Each provider declares a `get_cycle_length(entity_id)` method that returns minutes from a device-exposed sensor when available, else `None`. The coordinator falls back to `PROVIDER_AVG_CYCLE[provider_id][appliance_class]` constants. Constants live in `domain_coordinators/appliance_providers/_cycle_defaults.py` so they can be edited per-provider without rebuilds.

---

## ApplianceProvider ABC v2 — new methods + capability flags

Two new methods and two new capability flags relative to v1.1.

```python
# domain_coordinators/appliance_providers/base.py (extends v1.1 spec)

class ApplianceCapabilities:
    supports_delay_start: bool
    supports_remote_start: bool
    supports_pause: bool
    supports_cancel: bool                # NEW — required for interrupt-at-start
    interruptible_at_start: bool         # NEW — gating flag for principle 1 caveat
    delay_unit: Literal["minutes", "days"]
    max_delay: int
    cycle_length_sensor_pattern: str | None  # NEW — e.g. "sensor.{entity}_remaining_time"

class ApplianceProvider(ABC):
    # ... v1.1 methods ...

    @abstractmethod
    async def cancel_started_cycle(
        self,
        entity_id: str,
        reason: str,
    ) -> ProviderResult:
        """NEW. Stop a cycle that has just started but not materially begun.
        Returns ProviderResult with `original_command_payload` populated so the
        coordinator can persist enough state to resume later via set_delay_start.
        Providers that cannot safely cancel return ProviderResult(ok=False,
        reason='not_interruptible')."""

    @abstractmethod
    async def get_cycle_length(self, entity_id: str) -> int | None:
        """NEW. Return remaining cycle minutes from a device sensor, or None
        if no such sensor is exposed. Coordinator falls back to PROVIDER_AVG_CYCLE."""

    @abstractmethod
    async def get_power_draw_w(self, entity_id: str) -> tuple[float, float] | None:
        """NEW. Return (watts, age_seconds) from the device-native power entity.
        None if no native entity. The coordinator combines this with a separately-
        configured mains-circuit monitor to make the interrupt-at-start decision."""
```

`ProviderResult` gains a `payload: dict | None` field for `cancel_started_cycle` to thread the original command (cycle, options) back for restoration.

LGThinQProvider sets `supports_cancel=True`, `interruptible_at_start=True` for washers/washtowers/dishwashers (LG appliances accept STOP before water-draw; we treat post-water as materially started). RainbirdProvider sets `supports_cancel=False`, `interruptible_at_start=False` (rain delay covers the future-only semantics).

---

## Strictness Config Schema

Per-appliance options-flow schema (lives under `cm_entry.options["appliance_scheduler"]["appliances"][entity_id]`):

```python
{
    "enabled": bool,                          # global per-appliance gate
    "target_period": Literal["off_peak", "off_or_mid_peak"],  # was hard-coded off_peak in v1.0
    "tolerate_mid_peak": bool,                # convenience alias; sets target_period
    "on_bisect": Literal["stop", "start", "prefer_off_peak"],
    "cycle_length_source": Literal["sensor", "fallback"],
    "fallback_cycle_minutes": int | None,     # if cycle_length_source=fallback
    "interrupt_manual_start": bool,           # principle 1 opt-in per appliance
    "max_delay_minutes": int,
    "device_power_sensor": str | None,        # entity_id
    "circuit_power_sensor": str | None,       # entity_id
    "energy_per_cycle_kwh": float | None,     # savings estimate input
}
```

**Mirror to runtime entities (per principle 9):**
- `switch.ura_appliance_<id>_scheduling_enabled`
- `switch.ura_appliance_<id>_interrupt_manual_start`
- `select.ura_appliance_<id>_on_bisect` (options: stop / start / prefer_off_peak)
- Per-appliance `number.ura_appliance_<id>_max_delay_minutes` is NOT created — per the configurability memo (named-bucket dropdowns over runtime Number entities); use a `select` with discrete buckets (15min / 60min / 4h / 8h / overnight) instead.

---

## TOU Bisect Decision Pseudocode (Principle 11)

Reproduces v1.1 with one refinement: when both `tolerate_mid_peak=True` AND `target_period=off_or_mid_peak`, the bisect check uses "minutes until peak" — so mid-peak is treated as safe.

```python
async def evaluate_manual_start(entity_id: str) -> Decision:
    cfg = self._refresh_config()                                     # Bug #14
    opts = cfg["appliances"][entity_id]
    if not opts["enabled"] or not opts["interrupt_manual_start"]:
        return Decision.ALLOW

    tou = self._energy_coord.tou_engine if self._energy_coord else None
    if tou is None:
        return Decision.ALLOW                                        # principle 6

    current_period = tou.get_current_period()
    target_period = opts["target_period"]                            # 'off_peak' | 'off_or_mid_peak'

    # Already in allowed period -> allow
    if current_period in _allowed(target_period):
        return Decision.ALLOW

    # Bisect math (principle 11)
    minutes_until_safe = tou.get_minutes_until_period(
        target_period="off_peak" if target_period == "off_peak" else "off_or_mid_peak"
    )
    minutes_until_peak = tou.get_minutes_until_period(target_period="peak")
    cycle_minutes = (
        await provider.get_cycle_length(entity_id)
        if opts["cycle_length_source"] == "sensor"
        else None
    ) or opts.get("fallback_cycle_minutes") or PROVIDER_AVG_CYCLE[provider_id]

    if minutes_until_peak is None or cycle_minutes <= minutes_until_peak:
        return Decision.ALLOW                                        # completes before peak

    match opts["on_bisect"]:
        case "prefer_off_peak":
            return Decision.INTERRUPT_AND_DEFER(reason="cycle_bisects_peak",
                                                target_minutes=minutes_until_safe)
        case "start":
            return Decision.ALLOW_WITH_NOTIFY(reason="user_override_bisect")
        case "stop":
            return Decision.INTERRUPT_AND_NOTIFY(reason="cycle_bisects_peak")
```

`Decision.INTERRUPT_AND_DEFER` triggers the SM's EVALUATING → INTERRUPTED edge.

---

## Power Monitoring Multi-Vector Architecture

Three responsibilities, in priority order:

1. **`PowerSignalAggregator(hass, opts)`** — helper at `domain_coordinators/appliance_providers/_power_signal.py`. Owns the freshness budget.
   - Reads `opts["device_power_sensor"]` and `opts["circuit_power_sensor"]`.
   - Returns `PowerReading(watts, age_seconds, source)`.
   - Policy: prefer device-native if `age_seconds <= 30`; else circuit with `age_seconds + freshness_penalty`; else `None`.

2. **Coordinator polling cadence.** When evaluating "did the user just press START?", the coordinator does NOT issue cancel within 30s of the suspected start unless `age_seconds < 30` for the chosen source. This prevents false-positive interrupts during legitimate ramps.

3. **State-listener trigger.** Both vectors are listened to via `async_track_state_change_event` (uses the entity_id-stable pattern at `domain_coordinators/hvac.py:194` for `_pending_tasks` tracking). When either vector crosses an idle→active threshold, the coordinator runs `evaluate_manual_start`.

**Disagreement resolution** (per v1.1 principle 8): device-native within 30s freshness wins; otherwise circuit monitor with a logged-and-counted freshness penalty (sensor `..._power_freshness_penalty_events_today`).

---

## State Machine v2 (with INTERRUPTED state)

```
   user/integration -> "ready_to_start"
                |
                v
        EVALUATING --(provider unreachable)---> DROPPED
            |   |
            |   +--(manual start in bad window)--> INTERRUPTED --> SCHEDULING
            |                                                          |
            |                                                          v
            v (TOU off-peak? minutes=0; else compute)              [resumes via
        SCHEDULING                                                  set_delay_start
            |  (provider returns OK)                                 with restored payload]
            v
        ARMED --(user cancels at appliance)--> CANCELLED
        |  +--(integration unavailable > 30m)--> DROPPED + notify
        |
        (delay timer fires)
                v
        EXPECTING_RUN --(no run within 15m)--> ANOMALY (log; no retry)
                |
                v
          RUNNING --> COMPLETE
```

**INTERRUPTED is a distinct state from SCHEDULING.** It carries:
- `original_command_payload: dict` (cycle, options) — needed for `set_delay_start(payload=...)` to restore
- `interrupted_at: datetime`
- `reason: Literal["cycle_bisects_peak", "in_peak_window"]`

INTERRUPTED transitions to SCHEDULING on the next evaluation tick. Persisted to DB so a restart during INTERRUPTED resumes correctly.

---

## Deliverables (12)

### D1: ApplianceProvider ABC v2 + LGThinQProvider with cancel + cycle-length + power
**What:** v1.1 D1 PLUS the three new abstract methods (`cancel_started_cycle`, `get_cycle_length`, `get_power_draw_w`) and the two new capability flags (`supports_cancel`, `interruptible_at_start`). LGThinQProvider implements all three; verifies service surface via `hass.services.async_services()` (per v1.1 open question #1).

**Files:** `domain_coordinators/appliance_providers/base.py`, `domain_coordinators/appliance_providers/lg_thinq.py`, `domain_coordinators/appliance_providers/_cycle_defaults.py` (constants).

**Bug class prevention:** #22 (StrEnum), #29 (every status branch has populator), #37 (API contract — new abstract methods force every provider to implement; ABC enforces).

**Acceptance Criteria:**
- **Verify:** All 6 LG appliances enumerate; all return `interruptible_at_start=True`.
- **Verify:** `LGThinQProvider.cancel_started_cycle(entity_id, reason)` returns `ProviderResult(ok=True, payload={"cycle": "<name>", ...})`; idempotent (second call returns `ok=True, no_op=True`).
- **Verify:** `get_cycle_length(washer)` returns a positive int when remaining-time sensor present, else `None`.
- **Sensor:** `sensor.ura_appliance_coordinator_provider_status` exposes per-provider availability + capability flags.
- **Test:** `test_lg_thinq_cancel_started_cycle_returns_payload`, `test_lg_thinq_cycle_length_sensor_path`, `test_lg_thinq_cycle_length_no_sensor_returns_none`, `test_provider_abc_enforces_new_methods`.
- **Live:** Manually press START on a washer during peak; observe URA issuing the cancel service call within 30s; `sensor.ura_appliance_coordinator_last_blocked_start` updates.

---

### D2: Appliance Coordinator core with strictness flow + interrupt path
**What:** v1.1 D2 PLUS: `evaluate_manual_start()` method implementing the bisect pseudocode; INTERRUPTED state handling; `_refresh_config()` returns merged strictness opts per appliance; integration with `PowerSignalAggregator` (D11).

**Files:** `domain_coordinators/appliances.py`, `domain_coordinators/signals.py` (new constants).

**New signals:**
- `SIGNAL_APPLIANCE_INTERRUPTED` (payload: `{entity_id, reason, original_command_payload}`)
- `SIGNAL_APPLIANCE_RESUMED` (payload: `{entity_id, deferred_until}`)
- `SIGNAL_APPLIANCE_DEFERRED`, `SIGNAL_APPLIANCE_RUNNING`, `SIGNAL_APPLIANCE_COMPLETE` (from v1.0)

**Bug class prevention:** #1 (lifecycle), #2/#14 (config refresh), #19 (`_pending_tasks` per `hvac.py:194`), #23 (observation mode at every dispatch site), #37 (signal payloads stable).

**Acceptance Criteria:**
- **Verify:** Coordinator registers in CM with priority 25; survives `async_stop`/`async_start`.
- **Verify:** Triggering a manual start during peak with `interrupt_manual_start=True` fires `SIGNAL_APPLIANCE_INTERRUPTED` exactly once; state machine reaches INTERRUPTED then SCHEDULING within one tick.
- **Verify:** With `interrupt_manual_start=False`, manual start during peak is ignored (no cancel issued).
- **Sensor:** `sensor.ura_appliance_coordinator_pending_deferrals` reflects ARMED + INTERRUPTED + SCHEDULING counts.
- **Test:** `test_evaluate_manual_start_allows_in_off_peak`, `test_evaluate_manual_start_interrupts_in_peak_when_bisect_set`, `test_evaluate_manual_start_respects_tolerate_mid_peak`, `test_interrupted_state_persists_payload`, `test_pending_tasks_cancelled_on_teardown`.
- **Live:** Press start during peak with `on_bisect=prefer_off_peak`; observe interrupt + arming for the next off-peak boundary.

---

### D3: TOU `get_minutes_until_period` bidirectional helper (was v1.0 D3, refined)
**What:** Extend `domain_coordinators/energy_tou.py` (after line 235) with `get_minutes_until_period(target_period: str, now=None) -> int | None`. Accepts `peak`, `mid_peak`, `off_peak`, `off_or_mid_peak` (composite). Validates against `_VALID_PERIODS` at line 37. Walks the season's transition list; minute-precise delta from `now`. Handles cross-day wrap.

**Files:** `domain_coordinators/energy_tou.py` only. No behavior change to existing callers.

**Bug class prevention:** #11 (timezone — use `dt_util.now()`), #22 (composite period validated explicitly).

**Acceptance Criteria:**
- **Verify:** At 15:30 with peak 16:00-21:00, `get_minutes_until_period("peak")` returns 30; `get_minutes_until_period("off_peak")` returns 330.
- **Verify:** During off_peak, `get_minutes_until_period("off_peak")` returns 0.
- **Verify:** `get_minutes_until_period("off_or_mid_peak")` during peak returns minutes until the earlier of mid_peak or off_peak transition.
- **Test:** `test_minutes_until_peak_at_30_minutes`, `test_minutes_until_composite_off_or_mid_peak`, `test_minutes_until_period_dst_transition`, `test_minutes_until_period_invalid_target_raises`.
- **Live:** `sensor.ura_energy_coordinator_tou_status` exposes both `minutes_until_off_peak` AND `minutes_until_peak` attributes.

---

### D4: Persistence — deferrals AND stalled starts
**What:** v1.0 D4 PLUS: a `stalled` row type distinct from a `deferred` row. URADatabase methods:
- `save_appliance_sm_row(deferral_id, state, payload_json)` — generalized
- `load_pending_sm_rows()` — returns all non-terminal rows
- `delete_appliance_sm_row(deferral_id)`
- `cleanup_appliance_sm_rows(retention_days=14)` — batched per Bug #25

Schema:
```sql
CREATE TABLE appliance_state_machine (
    id INTEGER PRIMARY KEY,
    deferral_id TEXT UNIQUE NOT NULL,
    entity_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    state TEXT NOT NULL,                    -- EVALUATING, INTERRUPTED, SCHEDULING, ARMED, ...
    target_run_time TEXT,                   -- ISO 8601
    original_command_payload TEXT,          -- JSON; NULL except in INTERRUPTED
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_appliance_sm_state ON appliance_state_machine(state);
CREATE INDEX idx_appliance_sm_entity ON appliance_state_machine(entity_id);
```

**On `async_setup`:** load every non-terminal row; for INTERRUPTED, re-evaluate immediately (may transition to SCHEDULING if window still bad); for ARMED, restore the timer per v1.0 D4 rules.

**Bug class prevention:** #10, #21 (timestamps via `dt_util.parse_datetime`), #25 (batched DELETE), #27 (cleanup registered in nightly maintenance), #29 (Unbudgeted Scheduled Maintenance — add to rotation), #39 (test fixtures extract schema from production DDL — Tier 2-DB requirement).

**Acceptance Criteria:**
- **Verify:** Manual start during peak → INTERRUPTED row persisted with `original_command_payload` non-NULL. Kill HA, restart 5 min later, row restored, evaluator picks up.
- **Verify:** Restart after target time long-past → row marked EXPIRED, no spurious service call.
- **Sensor:** `sensor.ura_appliance_coordinator_restored_deferrals` increments per restored row, with attribute `restored_by_state: {INTERRUPTED: N, ARMED: N, SCHEDULING: N}`.
- **Test:** `test_persist_interrupted_with_payload_and_restore`, `test_persist_armed_and_restore`, `test_expired_dropped`, `test_cleanup_appliance_sm_rows_batched`, `test_cleanup_registered_in_nightly_maintenance` (lint), `test_schema_extracted_from_production_ddl` (Bug #39 guard).
- **Live:** Stall a manual start; verify DB row via `ura-sqlite` MCP within seconds; restart HA; verify resume.

---

### D5: Reload resilience + reconciliation
**What:** v1.0 D5 unchanged in goal, but the reconciliation walk (every 5 min) now also covers INTERRUPTED rows: re-evaluates `evaluate_manual_start` semantics; transitions to SCHEDULING when the window flips.

**Files:** `domain_coordinators/appliances.py`.

**Bug class prevention:** #20 (no `async_update_entry` cross-entry from this coordinator), #22 (reconciliation compares `.value`), #38 (`async_listen` unsubs tracked).

**Acceptance Criteria:**
- **Verify:** Disable + re-enable LG ThinQ; INTERRUPTED/ARMED rows untouched; no double service call after reload.
- **Verify:** Reload Appliance Coordinator entry; in-memory SM rebuilt from DB; identical state.
- **Sensor:** `sensor.ura_appliance_coordinator_reconciliation_count` increments per walk; `attributes.last_reconciliation_summary` shows per-state counts.
- **Test:** `test_no_double_service_call_on_lg_reload`, `test_state_listener_uses_entity_id_not_object`, `test_reconciliation_transitions_interrupted_to_scheduling_at_period_flip`.
- **Live:** Reload LG ThinQ during ARMED; verify no extra service call in trace.

---

### D6: Failure-mode SM completion + observation mode + signals (v1.0 D6 + INTERRUPTED branches)
**What:** Complete the SM transitions in code, including the new INTERRUPTED branches. Wire observation mode gate at the dispatch boundary (Bug #23) for ALL new signals. Dispatch the new `SIGNAL_APPLIANCE_INTERRUPTED` and `SIGNAL_APPLIANCE_RESUMED`.

**Failure handling table** (extends v1.0):

| Failure | Response |
|---|---|
| Provider unreachable during INTERRUPTED → SCHEDULING transition | Stay in INTERRUPTED; reconciliation retries; after 30 min → DROPPED |
| `cancel_started_cycle` returns `ok=False, reason='not_interruptible'` | Log once, transition to RUNNING (allow cycle); count `interrupt_skipped_not_supported` |
| Power vectors disagree at start | Use the priority rule (D11); count freshness-penalty event |
| Observation mode ON during interrupt evaluation | Skip cancel + dispatch; log intent only |

**Bug class prevention:** #23 (every dispatch behind observation gate), #28 (async `add_update_listener`), #24 (lambda scope).

**Acceptance Criteria:**
- **Verify:** With observation mode ON, `evaluate_manual_start` runs but never calls `cancel_started_cycle`; logs intent.
- **Verify:** Provider `cancel` returns `ok=False, reason='not_interruptible'` → SM goes to RUNNING; `sensor.ura_appliance_coordinator_interrupt_skipped_today` increments.
- **Test:** `test_observation_mode_blocks_interrupt_at_dispatch`, `test_cancel_failure_falls_through_to_running`, `test_signal_interrupted_payload_shape`.
- **Live:** Toggle observation mode on; press START during peak; verify zero service calls, log entry only.

---

### D7: RainbirdProvider + forecast-aware skip (unchanged from v1.0/v1.1)
**What:** v1.0/v1.1 D7 verbatim. Rain delay translation, weather threshold, no active-cycle interrupt.

**Bug class prevention:** #8 (forecast dict guards), #11 (UTC→local), #26 (forecast cache TTL via `time.monotonic()`).

**Acceptance Criteria:** Identical to v1.0/v1.1 D7.

---

### D8: Rainbird master kill-switch (split out from D7 for clarity)
**What:** `switch.ura_appliance_coordinator_rainbird_enabled` as a discrete observable surface. When OFF, the coordinator does not call ANY Rainbird services — not `set_rain_delay`, not schedule reads. Mirrored in options-flow AND as a runtime switch entity (principle 9). Default ON when RainbirdProvider discovered.

**Files:** `domain_coordinators/appliances.py`, switch platform file (`switch.py` add entity class).

**Bug class prevention:** #35 (switch entity wired to a refresh signal), #32 (no orphan form field).

**Acceptance Criteria:**
- **Verify:** Toggling `switch.ura_appliance_coordinator_rainbird_enabled = OFF` halts all subsequent Rainbird service calls within one decision cycle; existing in-flight rain delays remain on the controller (URA does not clear them).
- **Verify:** Toggling back ON resumes forecast evaluation on next 30-min decision tick.
- **Sensor:** `sensor.ura_appliance_coordinator_rainbird_status` shows `enabled|disabled|no_provider`.
- **Test:** `test_rainbird_kill_switch_halts_service_calls`, `test_rainbird_kill_switch_restore`, `test_rainbird_status_sensor_populator` (Bug #29).
- **Live:** Flip switch off; manually trigger evaluation; confirm zero rainbird.* service calls in trace.

---

### D9: GenericPowerSensorProvider (v1.0 D8 verbatim, deferred to v4.8.0 ship)
**What:** v1.0 D8 unchanged. Read-only provider that watches `sensor.*_power` and emits cycle observations without control. Useful only after D11 lands the `PowerSignalAggregator`, because Generic is essentially "circuit-monitor only" with no device-native vector. Becomes a thin wrapper over `PowerSignalAggregator` rather than re-implementing thresholding.

**Acceptance Criteria:** v1.0 D8 verbatim.

---

### D10: Observability + Dashboard hooks (was D7.5; promoted to real deliverable)
**What:** Concrete entity slate. All entities use the device-info pattern from existing coordinators (HVAC at `domain_coordinators/hvac.py` is canonical).

**Sensors:**
- `sensor.ura_appliance_coordinator_pending_deferrals` — int + `attributes.deferrals: list[{appliance, target_run_time, reason, state}]`
- `sensor.ura_appliance_coordinator_last_blocked_start` — string + `attributes.timestamp, .resumed_at`
- `sensor.ura_appliance_coordinator_deferrals_today` — daily counter
- `sensor.ura_appliance_coordinator_savings_today_kwh` — Wh×rate-delta sum; resets daily
- `sensor.ura_appliance_coordinator_savings_today_dollars` — `kwh × tou_rate_delta`
- `sensor.ura_appliance_coordinator_anomaly_status` — `green|orange|red` per v4.6.11 health pattern
- `sensor.ura_appliance_coordinator_state_machine_breakdown` — counts per SM state
- `sensor.ura_appliance_coordinator_rainbird_status` — `enabled|disabled|no_provider` (D8)
- `sensor.ura_appliance_coordinator_provider_status` — per-provider availability (D1)
- `sensor.ura_appliance_coordinator_sprinkler_skips_today` — D7
- `sensor.ura_appliance_coordinator_interrupt_skipped_today` — D6 (count of `not_supported`)
- `sensor.ura_appliance_coordinator_power_freshness_penalty_events_today` — D11

**Switches:**
- `switch.ura_appliance_coordinator_scheduling_enabled` (global)
- `switch.ura_appliance_<id>_scheduling_enabled` (per-appliance)
- `switch.ura_appliance_<id>_interrupt_manual_start` (per-appliance)
- `switch.ura_appliance_coordinator_rainbird_enabled` (D8)

**Selects:**
- `select.ura_appliance_<id>_on_bisect` — stop / start / prefer_off_peak
- `select.ura_appliance_<id>_max_delay_bucket` — 15m / 1h / 4h / 8h / overnight

**Buttons:**
- `button.ura_appliance_coordinator_cancel_pending_deferrals`
- `button.ura_appliance_<id>_resume_now` — for INTERRUPTED entries, lets operator force resume

**Files:** `sensor.py`, `switch.py`, `select.py`, `button.py` (add classes; coordinator publishes via existing dispatch pattern).

**Bug class prevention:** #29 (every sensor has populator path tested), #32 (every form field has a runtime reader), #35 (buttons wired to refresh signal), #36 (per-zone dedup N/A here but check for per-appliance dedup analogue).

**Acceptance Criteria:**
- **Verify:** All entities listed appear on `URA: Appliance Coordinator` device page after setup with 6 LG appliances.
- **Verify:** `select.ura_appliance_<id>_on_bisect` change persists to options AND is picked up by next `_refresh_config()` (Bug #14) without restart.
- **Verify:** `button.ura_appliance_<id>_resume_now` on an INTERRUPTED entry triggers immediate SCHEDULING transition.
- **Sensor:** `..._anomaly_status` reports `green` when 0 drops in 24h, `orange` if drop_rate > 0, `red` if drop_rate > 20%.
- **Test:** AST-level smoke test enumerating expected unique_ids; behavioral test `test_resume_now_button_force_schedules`; populator coverage test per Bug #29.
- **Live:** Toggle each switch and verify behavior change reflected in next coordinator decision.

---

### D11: PowerSignalAggregator + multi-vector discipline (NEW)
**What:** Helper class at `domain_coordinators/appliance_providers/_power_signal.py`. Implements the priority/freshness policy described in the "Power Monitoring" section above. Consumed by D2 (interrupt detection) and D9 (generic provider).

**Files:** new `_power_signal.py`; no production files modified.

**Bug class prevention:** #11 (timestamp arithmetic — `dt_util.utcnow()` only; no `time.time()` mixed with HA states), #26 (don't poll the same sensor twice per tick — cache for 5s).

**Acceptance Criteria:**
- **Verify:** Device-native reading aged 10s returned with `source='device'`.
- **Verify:** Device-native reading aged 60s, circuit reading aged 25s → circuit returned with `source='circuit', freshness_penalty=True`.
- **Verify:** Both stale (>60s) → returns `None`; coordinator logs once.
- **Test:** `test_power_aggregator_prefers_device_when_fresh`, `test_power_aggregator_falls_back_to_circuit_when_device_stale`, `test_power_aggregator_returns_none_when_both_stale`.
- **Live:** Disconnect device-native power sensor; verify aggregator falls back to circuit + freshness penalty counter increments.

---

### D12: Cycle-length source-of-truth (NEW)
**What:** Per-provider `_cycle_defaults.py` with `PROVIDER_AVG_CYCLE: dict[provider_id, dict[appliance_class, int_minutes]]`. Coordinator consults via:
1. Try `provider.get_cycle_length(entity_id)` (sensor path);
2. Else `opts["fallback_cycle_minutes"]` (user override);
3. Else `PROVIDER_AVG_CYCLE[provider_id][appliance_class]`;
4. Else fail-safe constant (90 min) + warning.

**Files:** `domain_coordinators/appliance_providers/_cycle_defaults.py`.

Initial constants (LG ThinQ, researched defaults from v1.1 principle 7):
```python
PROVIDER_AVG_CYCLE = {
    "lg_thinq": {"washer": 50, "washtower": 60, "dishwasher": 120},
    "rainbird": {"sprinkler": 20},  # not used for bisect; informational
    "generic_power_sensor": {"unknown": 60},
}
```

**Bug class prevention:** #14 (refresh config so override takes effect without restart), #22 (appliance_class is a StrEnum).

**Acceptance Criteria:**
- **Verify:** With LG remaining-time sensor present, cycle length comes from sensor (live value).
- **Verify:** With sensor absent and `cycle_length_source=fallback`, cycle length comes from `PROVIDER_AVG_CYCLE`.
- **Verify:** User-set `fallback_cycle_minutes` overrides the constant.
- **Test:** `test_cycle_length_resolution_order`, `test_cycle_length_fallback_when_sensor_missing`, `test_cycle_length_warns_on_unknown_class`.
- **Live:** Edit per-appliance `fallback_cycle_minutes` in options-flow; next decision tick uses new value.

---

## Implementation Order + Dependency Graph

```
D3  (TOU bidirectional helper)          -- independently testable; ship first
D11 (PowerSignalAggregator helper)      -- independently testable; ship parallel with D3
D12 (Cycle-length defaults + resolver)  -- independently testable; ship parallel with D3
D1  (Provider ABC v2 + LGThinQ)         -- needs D11 (calls aggregator), D12 (cycle resolver)
D2  (Coordinator core + interrupt path) -- needs D1 + D3
D4  (Persistence: deferrals + stalled)  -- needs D2 (SM defined)
D5  (Reload resilience + reconcile)     -- needs D2 + D4
D6  (SM completion + observation + sig) -- needs D2 + D4
D10 (Observability slate)               -- needs D2 surface; can land entities incrementally
D7  (Rainbird + forecast skip)          -- parallel with D6; uses D6 dispatch
D8  (Rainbird kill-switch)              -- parallel with D7; needs D10 switch infra
D9  (GenericPowerSensorProvider)        -- parallel with D6; needs D11 (its only sensor source)
```

**Ship plan:**
- **v4.7.0** — D3, D11, D12, D1, D2, D4, D6, D10 (LG cost-deferral + interrupt + observability)
- **v4.7.1** — D5 (reload resilience hardening)
- **v4.7.2** — D7 + D8 (sprinkler skip + kill switch)
- **v4.8.0** — D9 (generic power sensor provider)

---

## Risk Register (revised)

| Risk | Severity | Mitigation |
|---|---|---|
| False-positive interrupt during legitimate ramp-up | HIGH | 30s freshness budget (D11); idle→active threshold requires sustained reading; per-appliance `interrupt_manual_start` opt-in (default per-appliance, can be OFF) |
| User confusion when device suddenly stops | HIGH | NM notification on every interrupt with reason + resume-time; `sensor.ura_appliance_coordinator_last_blocked_start` for visibility |
| Provider rejects `cancel_started_cycle` mid-flight | MEDIUM | SM transitions to RUNNING (cycle allowed); count + sensor (`interrupt_skipped_today`); no retry storm |
| INTERRUPTED row payload too large for write queue | MEDIUM | JSON payload capped at 4KB; truncate + log + still defer (cycle name + start args enough to resume) |
| Race: manual start fires while a SCHEDULING ARM is in flight | MEDIUM | Per-entity asyncio lock in coordinator; only one SM transition at a time per entity_id |
| Cycle-length sensor stale or wrong (LG remaining-time unreliable mid-cycle) | MEDIUM | D12 fallback hierarchy; D11 freshness check applies to cycle-length sensor too (>5 min stale → fallback) |
| Multi-vector disagreement gets ignored | LOW | `power_freshness_penalty_events_today` sensor surfaces this to user; alarm threshold via anomaly detector |
| Rainbird kill-switch toggled off mid-evaluation | LOW | Check switch state at every decision tick (`_refresh_config()` reads it); already covered by Bug #14 prevention |
| Schema migration: existing `appliance_deferrals` table from a hypothetical v1.0 deploy collides | LOW | We have NOT shipped v1.0 — clean install. Add explicit `IF NOT EXISTS` guard anyway |
| Test fixtures hand-copy DDL → drift (Bug #39) | MEDIUM | Tier 2-DB Review C explicitly checks fixtures derive schema from production source |

---

## Tier Classification — Tier 2-DB

**Verdict: Tier 2-DB (three parallel reviewers, framed differently).**

**Triggers** (per CLAUDE.md Tier 2-DB criteria):
1. **Touches DAO definitions in database.py** — D4 introduces `save_appliance_sm_row`, `load_pending_sm_rows`, `delete_appliance_sm_row`, `cleanup_appliance_sm_rows` and a new `appliance_state_machine` table.
2. **Migrates ≥3 callers to a new DAO** — D2, D5, D6 all write/read through these methods plus D4's restore path. Five+ call sites total.
3. **Changes payload shape of dispatched events** — New `SIGNAL_APPLIANCE_INTERRUPTED` carries `original_command_payload`, `SIGNAL_APPLIANCE_RESUMED` carries `deferred_until`. Both are new persisted-event shapes downstream NM consumers will gate on.
4. **Adds behavioral test infrastructure against real schema** — D4 tests must extract the `appliance_state_machine` DDL from production source per Bug Class #39.
5. **Followed by future schema work** — v4.8.0 generic provider expects to write into the same SM table; Tier 2-DB now prevents a re-migration later.

**Review framings:**
- **Review A — Data integrity + DB architecture preservation.** No regression in existing tables (anomaly_log, energy_state, routine_*). Index coverage for the two new indexes. Write queue unchanged. `cleanup_appliance_sm_rows` batched + budgeted. Schema migration idempotent.
- **Review B — Migration correctness + signal chain integrity.** Every SM transition produces equivalent rows and fires the correct dispatch. INTERRUPTED → SCHEDULING fires `SIGNAL_APPLIANCE_RESUMED` exactly once. No double-emit. Field-by-field payload comparison vs spec for both new signals.
- **Review C — New surfaces + test fixture authority.** D10's sensor/switch/select/button slate round-trips through options-flow + RestoreEntity. D1's new ABC methods are exercised by tests that drive provider implementations (not stub-only). D11/D12 helpers tested via behavioral paths, not internal-state inspection. Test fixtures extract schema from production DDL (Bug #39).

**Pre-deploy snapshot:** Capture baseline row counts in `anomaly_log` grouped by `(coordinator, severity, type)` AND a fresh `appliance_state_machine` row count of 0 (table didn't exist). Post-deploy ±25% comparison applies to anomaly_log; appliance_state_machine starts populating fresh.

**Review D (live validation):** Within 1 hour post-restart, verify at least one row appears in `appliance_state_machine` (manual or organic) with non-NULL `state`, non-NULL `entity_id`, non-NULL `created_at`. Sentinel-only rows = payload broken (v4.6.1.1 / v4.6.3 precedent).

---

## Open Questions (Flag for Implementation)

Carry forward from v1.1:
1. Exact LG ThinQ service surface (`set_delay_start` vs `wash_set_delay_start`) — verify in HA service registry at config-flow time.
2. Rainbird integration variant (official vs HACS) — verify before D7.
3. CM observation mode flag key — mirror HVAC at `domain_coordinators/hvac.py`.
4. Cycle kWh defaults for savings calc — confirm in D2 config-flow.

New for v2:
5. **What constitutes "materially started"?** First water-fill event? First motor draw > 200W sustained for 60s? Provider-specific. Default: any power draw > 200W for ≥60s = materially started; cancel is no longer attempted.
6. **Resume payload schema across LG firmware.** LG ThinQ cycle/options dict shape may differ across firmware. Capture as opaque `dict[str, Any]`; provider re-validates on resume.

---

## Estimated Line Counts

| Deliverable | Production | Test | Config / Platforms |
|---|---|---|---|
| D1 (provider ABC v2 + LGThinQ) | ~360 | ~230 | ~40 |
| D2 (coordinator core + interrupt) | ~480 | ~320 | ~80 |
| D3 (TOU helper) | ~50 | ~80 | 0 |
| D4 (persistence + stalled) | ~200 | ~220 | 0 |
| D5 (reload resilience) | ~90 | ~140 | 0 |
| D6 (SM completion + signals) | ~150 | ~180 | ~30 |
| D7 (Rainbird + forecast) | ~220 | ~180 | ~50 |
| D8 (Rainbird kill switch) | ~60 | ~80 | ~30 |
| D9 (generic power) | ~140 | ~90 | ~40 |
| D10 (observability slate) | ~220 (across sensor/switch/select/button) | ~200 | ~30 |
| D11 (PowerSignalAggregator) | ~120 | ~140 | 0 |
| D12 (cycle defaults + resolver) | ~60 | ~80 | 0 |
| **Total** | **~2150 lines** | **~1940 lines** | **~300 lines** |

(~55% larger than v1.0's ~1380/1150/240 — the interrupt path + observability slate + multi-vector helper account for most of the delta.)

---

## What's NOT in v2 (scope guards)

- Mid-cycle interrupt (running cycle pause). Out of scope. Only manual-start pre-material interrupt is in.
- Per-zone sprinkler rain skip (would need soil sensors).
- Demand-response (utility-driven event signaling).
- Per-appliance ML cycle-length prediction (D12 uses sensor or constant only).
- Pause-and-resume across TOU boundaries.
- Microwave / oven scheduling (no remote start, immediate-use devices).
- Gas dryer active control (no electric draw to defer; D9 covers it informationally).

---

## Live-Validation Acceptance Summary (post-deploy checklist)

| # | Check | Tool |
|---|---|---|
| 1 | All 6 LG appliances enumerated in config-flow | UI |
| 2 | Press START on a washer in peak with `interrupt_manual_start=ON` → washer stops within 30s | Manual + log |
| 3 | INTERRUPTED row in `appliance_state_machine` with `original_command_payload` non-NULL | `ura-sqlite` MCP |
| 4 | At peak end, washer auto-resumes via `set_delay_start` | HA log + appliance UI |
| 5 | `sensor.ura_appliance_coordinator_last_blocked_start` non-empty | HA UI |
| 6 | `sensor.ura_appliance_coordinator_savings_today_dollars` aligns with hand calc within 10% | manual math |
| 7 | Toggle `switch.ura_appliance_coordinator_scheduling_enabled = OFF` → no new ARMs for 1h | HA log |
| 8 | Toggle `switch.ura_appliance_coordinator_rainbird_enabled = OFF` → no `rainbird.*` calls | HA log |
| 9 | After HA restart, INTERRUPTED rows restored within 60s | log + DB |
| 10 | Zero stale-task warnings in HA log over 24h | log |
| 11 | `anomaly_log` row counts +/-25% vs pre-deploy baseline by (coordinator, severity, type) | `ura-sqlite` MCP |

---

## References to existing code (verified in session)

- `domain_coordinators/energy_tou.py:37` — `_VALID_PERIODS = {"peak", "mid_peak", "off_peak"}`
- `domain_coordinators/energy_tou.py:199` — `get_next_transition()` (existing whole-hour helper; D3 extends with minute-precise sibling)
- `domain_coordinators/hvac.py:194` — `self._pending_tasks: set[asyncio.Task] = set()` (canonical task-tracking pattern for D2)
- `domain_coordinators/coordinator_diagnostics.py:704` — `class AnomalyDetector` (principle 10)
- `domain_coordinators/coordinator_diagnostics.py:978` — `store_event` (anomaly dispatch entry)
- `domain_coordinators/coordinator_diagnostics.py:1024` — `load_baselines` (called from `async_start`)
- `domain_coordinators/coordinator_diagnostics.py:1104` — `save_baselines` (called after observation)
- `domain_coordinators/manager.py:236` — `register_coordinator` (registration site)
- `domain_coordinators/base.py:164` — priority docstring (`Safety=100, Comfort=20`; Appliance picks 25)
- `domain_coordinators/signals.py:12-64` — existing `SIGNAL_*` constants; D2 adds appliance signals here following the same `ura_*` naming
- `docs/QUALITY_CONTEXT.md` — bug classes #1, #2, #8, #10, #11, #14, #19, #20, #21, #22, #23, #24, #25, #26, #27, #28, #29, #32, #35, #37, #38, #39 referenced in D-by-D prevention notes
