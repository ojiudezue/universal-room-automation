# CRITIQUE — Optimization Coordinator Audit (2026-07-10)

**Reviewing:** `docs/planning/PLANNING_audit_optimization_coordinator.md` (filed 2026-07-02).
**Target HEAD:** v5.9.0 (develop tip).
**Scope:** validate every finding at file:line; verify tier classification against the v5.0.0–v5.2.1 write-flood incident; audit config-flow/entity/device surfaces; propose a build plan.

---

## 1. Verification of the Audit's Findings at Current HEAD

Every anchor in the audit was re-read at HEAD. All plan-anchors resolve; the underlying issues persist unchanged by v5.8.x / v5.9.0 (both were unrelated: v5.8.0 = reconcile-on-return, rolled back; v5.9.0 = census dedup).

### 1.1 Fix-forward table (audit §1.1) — CONFIRMED LANDED at HEAD

| Item | Verdict | HEAD anchor |
|---|---|---|
| Batched persistence (1 write / cycle) | LANDED | `optimization.py:3417-3441` `_persist_findings_batch` → `database.log_findings_batch` (`database.py:5034`, per audit) |
| Boot-storm suppression | LANDED | `optimization.py:3527-3588` `_should_skip_for_boot_storm` (uptime grace 3 cycles + unavailable-fraction 0.5) |
| One META sentinel / cycle | LANDED | `optimization.py:805-817`; cap-preserved at `_cap_findings:3506-3516` |
| Signal fan-out throttled | LANDED | `optimization.py:3470-3490` `_dispatch_findings_updated_signal` — single per-cycle fire; sensors ignore payload |
| Write-volume regression test | LANDED | referenced test at `quality/tests/test_optimization_coordinator.py:3411` (per audit; not re-run in critique) |
| Second-channel activity-log O(N) | LANDED | Buffers `_cycle_shadow_log_buffer` / `_cycle_clamp_log_buffer` at `optimization.py:530-531`; drained ≤2 rows at `_flush_cycle_activity_summaries:3662-3733`; buffers cleared even on skip path `optimization.py:867-868` |

**Verdict: the write-flood incident's fix-forward is fully in-tree.** The invariant the audit proposes (`≤2 findings batches, ≤2 activity rows, ≤1 signal, 0 service calls at L1`) is testable today.

### 1.2 MED / LOW findings — CONFIRMED at HEAD

- **MED-1 (boot-storm walk cost).** Re-verified `_should_skip_for_boot_storm:3549-3572` — walks every configured sensor of every room every cycle, no cache, no short-circuit inside the room loop. On a 30-room fleet with ~5 configured sensors, that is up to 150 `hass.states.get` per cycle even after boot. **Valid.**
- **MED-2 (shadow-accuracy samples RAM-only).** Re-verified `_shadow_accuracy_samples: list[tuple[str, bool]] = []` at `optimization.py:563`. No persistence hook in `_run_shadow_accuracy_validator:1067-1201`; sample list resets to `[]` on every `__init__`. With `OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS=7` and `MIN_SAMPLES=20` (`const.py:1699-1700`), a weekly HA restart makes "ready" unreachable. **Valid + load-bearing for L1→L2 promotion.**
- **MED-3 (dedup TTL decrement is per-finding, not per-cycle).** Re-verified `_notify_if_severe:3608-3615`: the `for k in list(self._notify_dedup_state.keys()): self._notify_dedup_state[k] -= 1` block runs every time the method is called, and the method is called **per finding** from `_run_cycle_body:848`. Ten HIGH findings in one cycle → 10 decrements → the intended `OPTIMIZER_NOTIFY_DEDUP_CYCLES=12` (`const.py:1740` per audit) window collapses to ~1.2 cycles. **Valid; more severe than "MED" if the operator ever has a bad night — silent per-cycle NM spam.** I would elevate to **HIGH** — this is the difference between a 5-min pager and a 1-hour pager.
- **LOW-1 (cap-of-caps).** Re-verified: Tier-1 is capped at `optimization.py:822` (`findings = self._cap_findings(findings)`), LLM tier is capped at `optimization.py:878` (`llm_findings = self._cap_findings(llm_findings)`), but `all_findings = list(findings) + list(llm_findings)` at `optimization.py:898` is assigned to `_last_findings` at :899 without a merged re-cap. `_last_findings` can peak at 2×100=200. **Valid.**
- **LOW-2 (rate-cap seed WARNING vs DEBUG).** Re-verified: `_LOGGER.debug(...)` at `optimization.py:649` inside a bare `except Exception:`. **Valid.**

### 1.3 Livability findings (audit §2) — CONFIRMED at HEAD

- **Silent stub dimensions still advertised.** `automation_responsiveness:1920-1934`, `energy_efficiency:1986-1998`, `setpoint_compliance:2000-2019` all return `[]` unconditionally, but they ARE in the evaluator tuple at `optimization.py:750-757` and get `ok` verdicts every cycle in `_compute_dimension_verdicts`. Operator sees "ok" and reasonably infers "rule ran and passed"; reality is "rule doesn't run." **Valid.**
- **META in display state.** `sensor.ura_optimizer_findings` (sensor.py:14265) — not re-audited in detail here; the audit's claim that META pollutes the display timeline is plausible given the sentinel is the only guaranteed row per cycle. Keep D7 in-scope.
- **L1→L2 promotion path uncodified.** No promotion-readiness attribute anywhere in `_compute_dimension_verdicts:953-993` or the reasoning sensor (`sensor.py:14348-14413`). **Valid.**

### 1.4 Gaps I found the audit did NOT catch

- **Device grouping is BETTER than the audit implies.** The audit's "livability §2.4" says OC controls "exposed via `CONF_OPTIMIZER_*` in Coordinator Manager options" but doesn't call out that at HEAD there IS a distinct OC device (`identifiers={(DOMAIN, "optimization_coordinator")}` at `sensor.py:13984`, `select.py:486`, `switch.py:4172`, `button.py:1604`). Per-room `RoomOptimizationHealthSensor` at `sensor.py:14449` correctly attaches to the Room device (via `UniversalRoomEntity` base) — this matches the DPM→HVAC-device prior art (v4.7.7) philosophically: coordinator-scoped health lives on the coordinator device, per-room mirror lives on the room. **No change needed for D-device.** The audit under-specified this; the plan should say "confirmed correct" not "should mirror."
- **`_notify_dedup_state` decrement operates on stringified keys but suppression-check uses `str(dkey)` (:3616-3626) — key type mismatch is not present, but a `tuple` dedup_key gets serialized with parentheses/commas which is fine for equality but hides collisions across cycles if a dimension ever emits a dedup_key with mutable inner values. Not a bug today; note-for-D1.**
- **Reentrancy guard `_cycle_running` (:588, :721-731) is NOT test-restart-safe.** If a test/harness raises inside `_run_cycle_body` before the `finally`, the flag can pin. The `try/finally` at :727-731 covers exceptions, so this is defensive-only. Non-actionable.
- **`_action_dispatch_history` seed is CAPPED at 200 rows (`optimization.py:611`).** In a pathological cycle where the operator manually presses "Run Cycle Now" many times or shifts to L2 briefly, `get_recent_optimization_findings(limit=200)` may not contain all `applied` rows within the last hour. Documented as best-effort in the code, but the audit's "restart resilience for the per-hour cap invariant" is stronger than the code delivers. **Add to D8 or a new LOW.**
- **Boot-storm gate re-walks all rooms EVEN WHEN uptime-grace is still active (:3545-3548 returns early, so this is FINE)** — apparent audit implication that walk always runs is wrong for the first 3 cycles. But once past uptime grace, the walk runs unconditionally forever. MED-1 remains valid for the steady-state case.

### 1.5 Items the audit dropped from the incident's fix-forward list

The audit's Table §1.1 says "every item is present and wired." Cross-checking against the incident memo (`project_optimizer_db_write_flood_incident_2026_06_09`):

- Batch writes ✅
- Suppress boot-transient findings ✅ (boot-storm gate)
- Drop per-cycle sentinel flood ✅ (single META)
- Throttle per-room sensors ✅ (single signal / cycle, sensors ignore payload)
- Write-volume test ✅

Nothing dropped. But the audit does NOT propose **an in-code rollback tripwire** (e.g., a "if this cycle would produce >K writes, log CRITICAL and skip"). Given the incident memory is only 4 weeks old and the code has NO circuit-breaker beyond `_cap_findings`, I would ADD a deliverable D9: **runtime write-volume tripwire** (below).

---

## 2. Tier Classification

**Audit proposes: Tier 2-DB (3 framing-disjoint reviews).**

**My recommendation: elevate to Tier 3 (4 framings incl. adversarial-completeness).**

Rationale, mapping onto the CLAUDE.md Tier-3 trigger criteria:

- **Trigger 1 (state-machine / shared primitive; one-missed-site = failure).** MED-3's TTL decrement is exactly Bug Class #53 shape ("computed but not consumed correctly"). The dedup dict is a shared primitive; the fix could be applied at the "wrong per-cycle hook" and silently regress. This IS the failure mode Tier 3 exists for.
- **Trigger 2 (cost/safety-adjacent).** OC findings drive climate targets. MED-2 (persist shadow samples) is the gating primitive for future L1→L2 promotion — a mis-persisted sample = a wrongly-"ready" oracle = premature L2 = wrong HVAC nudges.
- **Trigger 3 (history of multi-fix-up cycles).** v5.0.0/5.1.0/5.2.0/5.2.1 → ROLLBACK → v5.3.0 re-deploy. The area has already burned through a live-house outage this year.
- **Standing policy (operator, 2026-06-08):** default to Tier 2-DB / Tier 3 for regression-prone work.

**Falsifiable invariant (state up-front, per Tier 3 discipline):**
> "For any cycle at `DEFAULT_OPTIMIZER_AUTONOMY_LEVEL = OPTIMIZER_LEVEL_SHADOW`: `hass.services.async_call` calls attributable to `_apply_action` == 0; `database.log_findings_batch` calls ≤ 2; `SIGNAL_OPTIMIZER_FINDING_EMITTED` dispatches == 1; `ura_activity_log` INSERTs from OC ≤ 2; `notification_manager.async_notify` calls per unique `dedup_key` in any 1-hour window ≤ 1 — regardless of finding count and regardless of how many severe findings share a cycle."

The audit's own invariant (§Falsifiable invariant) covers the first four clauses well but **omits the NM dedup clause** — which is exactly the MED-3 defect. **Add it.** Reviewer D's mutation targets must include the TTL decrement site.

### 2.1 Framings (four disjoint)

- **A — correctness / edge-cases.** boot-storm gate walk cost (MED-1), dedup TTL semantics (MED-3), cap-of-caps on merged findings (LOW-1), rate-cap seed logging (LOW-2), sample-store schema soundness (D2).
- **B — persistence + restart + cross-coord ripple.** New `optimizer_shadow_samples` table migration safety; existing `optimization_findings` unchanged (row-rate ±25% pre/post snapshot required); pruner introduced; ripple into NM (does a dedup-fix change NM's downstream de-dup expectations?); Bayesian predictor read path unchanged; per-room `RoomOptimizationHealthSensor` device attachment unchanged.
- **C — test authority via per-site source mutation.** Mutate ONE of: `_persist_findings_batch`, `_dispatch_findings_updated_signal`, `_flush_cycle_activity_summaries`, `_apply_action` shadow branch, the fixed dedup decrement hook, and the new sample-persist call. Each mutation must fail exactly one test.
- **D — adversarial completeness (diff-blind).** Re-enumerate every emission / persistence / dispatch site (existing AND new) and confirm the invariant. Concrete-repro requirement for any flagged leak. Emphasis: the LLM tier (`optimization_llm.py`) is a second emission path — must be enumerated end-to-end for the batched-persist invariant, not just Tier-1.

### 2.2 Mandatory pre-deploy artifacts (Tier 3)

- **Pre/post row-rate snapshot** of `optimization_findings` grouped by `(created_by, dimension, severity)` and of `ura_activity_log` filtered on `coordinator='optimization'`. ±25% is the pass gate.
- **Write-volume regression test** upgraded: assert both `log_findings_batch` count AND `ura_activity_log` INSERT count in a synthetic 100-finding, 10-severe cycle.
- **Runtime tripwire** (see D9 below).
- **Operator checkpoint** before deploy (Tier 3 discipline; the last OC deploy took the house down).

---

## 3. Context-Wide Scoping (Operator Directive 1)

OC surfaces read/written at HEAD (verified with grep):

**Reads (input surfaces):**

- Per-room ConfigEntry data+options: `CONF_TEMPERATURE_SENSOR`, `CONF_HUMIDITY_SENSOR`, `CONF_OCCUPANCY_SENSORS`, `CONF_MOTION_SENSORS`, `CONF_MMWAVE_SENSORS`, `CONF_COMFORT_TEMP_MIN/MAX`, `CONF_COMFORT_HUMIDITY_MAX` — via `_iter_room_entries:1471` + `_read_per_room_comfort:1484`.
- CM ConfigEntry options: `CONF_OPTIMIZER_AUTONOMY_LEVEL`, `_CONFIDENCE_GATE`, `_DIMENSION_AUTONOMY`, `_KILL_SWITCH`, `_QUIET_HOURS_SOURCE`, `_RATE_CAP_PER_HOUR`, `_SAFETY_DENY_ENTITIES` — via `_read_cm_config:2564`.
- Sibling coordinators (via CoordinatorManager): HVAC coordinator (`_get_hvac_coordinator:1534`) → `zone_manager` (`_iter_hvac_zones:1774`), `egress_manager` (`_get_egress_manager:1556`), `compliance_tracker` (referenced, deferred), `override_arrester` (via broker).
- HouseStateMachine: `_get_house_state_machine:1793` (used for `state_machine_accuracy` and `security_posture` gating).
- SecurityCoordinator: `_get_security_coordinator:1807` → `get_security_aggregator_state()`.
- BayesianPredictor: `_get_bayesian_predictor:2255` → `get_accuracy_stats`, `is_learning_suppressed`, `quality_report`; plus direct read of `prediction_results` table (`_read_next_room_accuracy:2267-2357`).
- NotificationManager: `is_quiet_hours_active` (`_is_quiet_hours_active:2583`), `async_notify` (`_notify_if_severe:3630`).
- Database DAOs: `log_findings_batch`, `get_recent_optimization_findings`, `log_daily_digest`, `_db_read` (for prediction_results direct SELECT).
- ActivityLogger: `activity_logger.log` (`_log_activity:3735`).

**Writes / emits (output surfaces):**

- `database.log_findings_batch` (1-2 batched writes / cycle) — table `optimization_findings`.
- `database.log_daily_digest` — daily row, dedup UNIQUE(date).
- `activity_logger.log` (≤2 summary rows / cycle) — table `ura_activity_log`.
- `SIGNAL_OPTIMIZER_INTENT`, `SIGNAL_OPTIMIZER_INTENT_VETO`, `SIGNAL_OPTIMIZER_FINDING_EMITTED` (`signals.py:164-166`).
- `hass.services.async_call` (L2+ only; currently gated by default L1).
- `notification_manager.async_notify` (severe findings; MED-3 fix required).
- Broker → HVAC `OverrideArrester.suppress/unsuppress` (L2+ climate actions).

**Consumers of OC outputs (verified via grep):**

- `OptimizerStatusSensor`, `OptimizerFindingsSensor`, `OptimizerReasoningSensor`, `OptimizerRoomHealthSensor` (all on `optimization_coordinator` device — `sensor.py:13984`).
- `RoomOptimizationHealthSensor` (per-room device — `sensor.py:14449`).
- `select.ura_optimizer_autonomy_level` (`select.py:451`, on optimization_coordinator device).
- `switch.ura_optimizer_kill_switch` (`switch.py:4151`).
- `button.ura_optimizer_confirm_escalation / cancel_escalation / reset_settings / run_cycle_now` (`button.py:1709-1919`).
- NM daily digest hook (`notification_manager.py:2122` `ura_optimizer_persist_daily_digest`).
- LLM Tier-2 wrapper (`optimization_llm.py`) — consumes Tier-1 findings, produces Tier-2 findings through same chokepoint.

**Cross-cutting implication for the plan:** MED-3 fix (dedup TTL) is NM-adjacent — it changes when the OC calls `nm.async_notify`. Reviewer B (persistence + cross-coord) must verify NM's internal dedup is not doing the same debounce (double-suppression risk). D2 (persist shadow samples) is DB-adjacent — Reviewer B must run pre/post row-rate on both tables. D5 (retire stub dimensions from the operator surface) is UX-adjacent — verify the reasoning-sensor renders correctly with a shorter verdict map (`sensor.py:14348-14413`).

---

## 4. Livability Design (Operator Directive 2)

### 4.1 Config-flow field audit

CM options keys touching OC (verified above): `autonomy_level`, `confidence_gate`, `dimension_autonomy`, `kill_switch`, `quiet_hours_source`, `rate_cap_per_hour`, `safety_deny_entities`.

Legibility issues to fix in-cycle (form-field labels — "Number Fields = Form Fields", per operator-coined phrasing in MEMORY.md):

- `CONF_OPTIMIZER_DIMENSION_AUTONOMY` — today accepts arbitrary dim keys including the stub dimensions. **Recommendation:** hide stubs from the selector until the stub-retirement (D5) lands, or gray them out with a "(not yet implemented)" suffix.
- `CONF_OPTIMIZER_CONFIDENCE_GATE` — a raw float [0..1]. **Recommendation:** in-form helper text "Findings below this confidence are logged but never actuated" (livability).
- `CONF_OPTIMIZER_RATE_CAP_PER_HOUR` — int. **Recommendation:** helper "Max L2+ actions per rolling hour (advisory / shadow are uncapped)".

### 4.2 Entity naming

Currently: `sensor.ura_optimizer_status`, `_findings`, `_reasoning`, `_room_health`; `select.ura_optimizer_autonomy_level`; `switch.ura_optimizer_kill_switch`; `button.ura_optimizer_{confirm_escalation, cancel_escalation, reset_settings, run_cycle_now}`. **Naming is coherent** — no rename needed. Per-room `sensor.{room}_optimization_health` (per `sensor.py:14461`) is clear.

### 4.3 Per-room sensor value semantics

Per-room `sensor.{room}_optimization_health` returns `opt.get_room_score(room)` (default 100.0). Attribute `degraded_dimensions` is a list of dimension names (`sensor.py:14497-14507`).

**Problems:**

- A room with no findings shows `100.0` — indistinguishable from "OC never ran" vs "OC ran, clean." Bug Class #5 nudge: use `None` until first cycle completes; add `last_cycle_at` attribute so the operator can see freshness.
- `degraded_dimensions` includes stub dimensions that never fire — but only after D5 makes this meaningful.
- No exposed reason for the score (which finding lowered it, when). **Recommendation:** attribute `worst_open` = `{dimension, severity, description, timestamp}` for the highest-severity finding contributing to the score.

### 4.4 Silent stub retirement (audit D5)

Concur, and add: emit a distinct `stub` verdict token from `_compute_dimension_verdicts` so `dimension_verdicts` can render as `{comfort: "ok", automation_responsiveness: "stub"}` — this is more discoverable than silently removing keys.

---

## 5. Device Entries (Operator Directive 3)

**Current state (verified at HEAD, contradicts audit implication):**

- Dedicated device: `identifiers={(DOMAIN, "optimization_coordinator")}` — hosts `OptimizerStatusSensor`, `OptimizerFindingsSensor`, `OptimizerReasoningSensor`, `OptimizerRoomHealthSensor` (`sensor.py:13984`, base `_OptimizerCMSensorBase:13993`), plus the autonomy `Select`, kill-switch `Switch`, and four `Button`s.
- Per-room mirror: `RoomOptimizationHealthSensor` (`sensor.py:14449`) inherits `UniversalRoomEntity` → attaches to the Room device (`via_device` = coordinator manager via Room base).

**Prior art:** DPM was moved from CM device to HVAC Coordinator device in v4.7.7 (see MEMORY entry `dpm_sensor_cleanup_backlog` and `project_v477_live`). This established the pattern: coordinator-owned diagnostic entities live on the coordinator's own device, per-room mirrors live on the room device.

**Current OC placement matches the prior-art pattern.** No mirroring change needed. The plan should call this out as "confirmed correct" rather than proposing changes; the audit under-specified this.

---

## 6. Observability + Controls per Deliverable (Operator Directive 4)

### D1 (Fix NM dedup TTL) — audit's MED-3, elevated to HIGH

- **Control surface:** none new — the fix is internal.
- **Sensors/attributes:** add attribute `notify_dedup_active_keys` (int) and `notify_dedup_next_expiry_iso` on `sensor.ura_optimizer_reasoning`. **Livability:** operator can see "3 severe findings are being suppressed for another 47 min."
- **Kill-switch placement:** existing `switch.ura_optimizer_kill_switch` already halts actuation; no new kill needed. Add: if `switch` is engaged, drain the dedup dict on the SAME event-loop tick so re-engagement produces clean state.
- **Test:** `test_optimizer_notify_dedup_ttl_decrements_per_cycle` — 10 HIGH findings, 10 distinct dedup keys, one cycle → each key TTL == `OPTIMIZER_NOTIFY_DEDUP_CYCLES - 1`.

### D2 (Persist shadow-accuracy samples) — audit's MED-2

- **Schema:** new table `optimizer_shadow_samples(observed_at TEXT, dimension TEXT, target_id TEXT, matched INTEGER)` + index `(observed_at)`; pruner mirroring `prune_optimization_findings`.
- **Sensors:** `shadow_accuracy_pct`, `shadow_accuracy_status`, and NEW `shadow_accuracy_samples_count` attributes on `sensor.ura_optimizer_reasoning`.
- **Kill-switch:** no new kill; sample write is inside the `_run_shadow_accuracy_validator` try/except.
- **Test:** DAO round-trip using the REAL schema fixture (not hand-copied DDL). **Live:** restart HA, verify `shadow_accuracy_pct` continuity within one cycle's drift.

### D3 (Cap merged findings) — audit's LOW-1

- Trivial internal fix: apply `_cap_findings` to `all_findings` before assignment to `_last_findings` at `optimization.py:898`.
- **Test:** synthetic dual-tier flood asserts `len(_last_findings) <= 100`.

### D4 (Boot-storm gate short-circuit + cache) — audit's MED-1

- **Control surface:** none new.
- **Sensor attribute:** `boot_storm_cache_expires_iso` on `sensor.ura_optimizer_reasoning` — livability, operator sees when the gate will re-evaluate.
- Cache K = ~5 cycles (25 min) once cleared; short-circuit as soon as fraction threshold crossed inside the room loop.
- **Test:** 30-room fleet, 3-cycle sequence, count `_state_value` calls ≤ K + 30 (single walk + short-circuit checks).

### D5 (Retire stub dimensions from operator surface)

- **Control surface:** update `CONF_OPTIMIZER_DIMENSION_AUTONOMY` schema to skip stub keys (or gray them out).
- **Sensor:** `dimension_verdicts` map on `sensor.ura_optimizer_reasoning` emits `"stub"` for `automation_responsiveness / energy_efficiency / setpoint_compliance`.
- **Test:** verdict-map assertion.

### D6 (L1→L2 promotion readiness) — livability core

**This is the most important livability deliverable. Spec fully:**

- **New attribute** `promotion_readiness` on `sensor.ura_optimizer_reasoning`, shape:
  ```python
  {
    "comfort": {
      "ready": bool,
      "current_level": "L1",
      "eligible_level": "L2",
      "blocked_by": [str, ...],
      "evidence": {
        "samples": int,           # against MIN_SAMPLES=20
        "accuracy_pct": float,    # rolling window
        "window_days": int,
        "days_of_data": float,
      },
    },
    ...  # one entry per scorable dimension only
  }
  ```
- **Blocker tokens** (canonical set; extend the audit's list):
  - `samples_below_min` (samples < `OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES`)
  - `accuracy_below_threshold` (< NEW `OPTIMIZER_PROMOTION_ACCURACY_FLOOR_PCT` = 80.0)
  - `window_incomplete` (`days_of_data < OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS`)
  - `stub_oracle` (dimension is a stub; never promotable)
  - `kill_switch_engaged`
  - `dimension_autonomy_ceiling_below_L2`
  - `observation_incomplete` (findings emitted but observed_effect==None for >X% — the "wired-but-inert" B-MED-1 signature)
- **Ready gate (all AND):** samples ≥ 20 AND accuracy ≥ 80% AND days_of_data ≥ 7 AND !stub AND !kill_switch AND ceiling ≥ L2 AND observation_incomplete==False.
- **Control surface:** none new — this is READ-ONLY guidance. Promotion still happens via existing `select.ura_optimizer_autonomy_level` / dimension autonomy dict.
- **Test:** synthesize a `_shadow_accuracy_samples` list; assert `ready==True` iff all conditions hold; enumerate each blocker.
- **Live:** initially all dimensions show `ready==False, blocked_by=["window_incomplete","samples_below_min"]`; after 7 days shadow accumulation on comfort, expect first `ready==True` observation.

### D7 (Exclude META from display state)

- **Control surface:** none.
- **Sensor:** `sensor.ura_optimizer_findings` `state` = latest NON-META `description`; META remains in DB.
- **Test:** cycle emitting ONLY the META sentinel → sensor state is `cycle_ok - no findings` (or the previous non-META, whichever is more consistent — pick one and document).

### D8 (Upgrade rate-cap seed logging) — audit's LOW-2

- Trivial: `_LOGGER.warning(...)` at `optimization.py:649` when seed exception fires.
- **Test:** monkeypatch DB to raise on seed; assert WARNING log.

### D9 (NEW — runtime write-volume tripwire; write-flood safeguard)

**Rationale:** the incident memory is only 4 weeks old; there is no runtime circuit-breaker beyond `_cap_findings` (which only bounds finding count, not DB writes if the invariant regresses). Add:

- **Counter:** `_cycle_db_write_count` reset each cycle; incremented in `_persist_findings_batch` and `_flush_cycle_activity_summaries`.
- **Tripwire:** if any cycle exceeds a hard ceiling (e.g. 5 DB writes), log CRITICAL and set an internal `_write_volume_alarmed` flag that suppresses subsequent OC persistence for the next K cycles (fail-closed).
- **Sensor:** `sensor.ura_optimizer_status` state becomes `"paused_write_flood"` while alarmed; attribute `write_volume_alarmed_at`.
- **Test:** force a regression (e.g. patch `_persist_findings_batch` to be called 10x); assert alarm fires and subsequent cycle skips persistence.

This is the "in-code rollback tripwire" the operator's brief asks for.

---

## 7. Institutional Context Verification

Audit §"Institutional Context Verified" — spot-checked:

- `OPTIMIZER_MAX_FINDINGS_PER_CYCLE: Final = 100` — verified at `const.py:1675` (audit said 1615 — **stale line number**; value correct).
- `OPTIMIZER_BOOT_SETTLE_CYCLES: Final = 3` — verified at `const.py:1681` (audit said 1621 — stale).
- `OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS = 7`, `MIN_SAMPLES = 20` — verified at `const.py:1699-1700`.
- `_persist_findings_batch` at `optimization.py:3417` (audit said 3417 — correct).
- `_dispatch_findings_updated_signal` at `optimization.py:3470` (audit correct).
- `_should_skip_for_boot_storm` at `optimization.py:3527` (audit correct).
- `_cap_findings` at `optimization.py:3492` (audit correct).
- `_apply_action` at `optimization.py:2844` (audit correct).

**Minor:** const.py line numbers in the audit are ~40 lines high (probably from a since-updated header). Values are right; audit should re-cite before the plan becomes a build spec.

---

## 8. Revised Build Order

Audit's order:
1. D5 + D7 (cheap, high livability)
2. D1 + D3 + D8 (bug fixes)
3. D4 (perf polish)
4. D2 (schema change)
5. D6 (rides on D2 + D5)

**Revised (Tier 3-aware):**

1. **D9** (runtime write-volume tripwire) — go first because it protects everything downstream during the build.
2. **D5 + D7** (cheap, low risk, pure UX).
3. **D3 + D8** (trivial fixes).
4. **D1 (HIGH)** (dedup TTL) — small code, high user impact; do this before persistence changes so review can concentrate.
5. **D4** (perf polish, wants live 5-cycle measurement post-deploy).
6. **D2** (schema change — Tier 3 focus of Reviewer B, real-schema fixture).
7. **D6** (rides on D2 + D5; the promotion-readiness attribute is the operator's roadmap to L2).

Non-goals unchanged from audit: no Phase 3.x stubs, no L2 enablement, no inclement-arbitrage-WAIT floor work (belongs to Energy Coord).

---

## 9. Biggest Risks

1. **MED-3 fix at the wrong place.** If the decrement moves to `_run_cycle_body` end but the finding emit path adds a new NM emission point (e.g., Phase-2 LLM tier), the guarantee re-breaks silently. Reviewer D MUST enumerate the LLM tier as a separate NM emission path.
2. **D2 sample table introduces a new write channel.** Pre/post row-rate snapshot on `optimization_findings` will look unchanged (that's the point) but if D2's write path fires per-sample per-cycle without batching, we recreate the incident on a different table. **Design D2 with a per-cycle batch write, not per-sample.**
3. **D6 promotion-readiness could silently green-light L2 on a stub-adjacent dimension** if the `stub_oracle` blocker is not computed correctly. Reviewer C (test-authority) must mutate the stub-token production and verify a test fails.
4. **D9 tripwire itself is a shared primitive.** If the counter is wrong, it can either (a) never fire (useless) or (b) always fire (silently break OC). Reviewer C mutation-tests must include this.
5. **Live-house risk.** OC is on the running system at L1 shadow. Any code path that accidentally moves a Phase-2 LLM finding to L2 is game-over. Standing L1 default MUST be re-verified post-deploy (test `test_optimizer_shadow_emits_intent_no_call` at `test_optimization_coordinator.py:649` per audit).

---

## 10. Testable Acceptance Criteria — Top Deliverables

### D1 (dedup TTL)
- **Test:** `test_optimizer_notify_dedup_ttl_decrements_per_cycle` — 10 HIGH findings, 10 distinct dedup_keys, single cycle → each key's cycles_remaining == `OPTIMIZER_NOTIFY_DEDUP_CYCLES - 1`.
- **Test:** `test_optimizer_notify_dedup_survives_flood` — 100 HIGH findings (same dedup_key) in one cycle → `nm.async_notify` called exactly once.
- **Live:** on running house, `sensor.ura_optimizer_reasoning.notify_dedup_active_keys > 0` for ~1h after a severe event, then drains.

### D2 (persist shadow samples)
- **Test:** DAO round-trip against real schema fixture; assert schema signature matches `optimization_findings` prune pattern.
- **Test:** `test_shadow_samples_persist_across_restart` — write 10 samples, tear down coord, re-init, verify 10 samples re-loaded.
- **Test:** `test_shadow_samples_batched_write` — 100 samples emitted in one cycle → 1 batched DB write, not 100.
- **Live:** restart HA; `sensor.ura_optimizer_reasoning.shadow_accuracy_pct` within ±0.5% of pre-restart value.

### D6 (promotion readiness)
- **Test:** for each canonical blocker token, construct minimal state that triggers it and assert `promotion_readiness.<dim>.blocked_by` contains it.
- **Test:** all conditions met → `ready==True` for `comfort`.
- **Live:** during first week post-deploy, `blocked_by` for `comfort` transitions `[window_incomplete, samples_below_min] → [samples_below_min] → []`.

### D9 (write-volume tripwire)
- **Test:** patch `_persist_findings_batch` to be called 10x in one cycle → alarm fires, `sensor.ura_optimizer_status.state == "paused_write_flood"`.
- **Test:** subsequent cycle while alarmed → 0 DB writes attempted.
- **Live:** boot-time snapshot of `_cycle_db_write_count == 0` after uptime-grace clears.

---

## Summary line for build orchestrator

Findings valid. Elevate to Tier 3 (4 framings). Elevate MED-3 to HIGH. Add D9 (runtime tripwire). Confirm device grouping already matches DPM prior art (no change). Build order: D9 → D5+D7 → D3+D8 → D1 → D4 → D2 → D6. Non-goals unchanged. Pre-deploy row-rate snapshot + operator checkpoint mandatory.
