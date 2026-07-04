# PLANNING — Audit of the Optimization Coordinator

**Status:** Audit + high-level plan (no source changes).
**Cycle target (if built):** post-v5.7.2, feature-cycle scope.
**Author:** ura-planner (senior architect pass).

---

## Institutional Context Verified

### Prior planning docs consulted
- `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR.md` (canonical multi-phase plan; Appendix A on comfort sliders, Appendix B on inclement arbitrage floor — full read).
- `docs/planning/RESEARCH_2026-05-13_HEMS_optimization_landscape.md` (filename only; not load-bearing here).

### Memory bodies pulled
- `project_optimizer_db_write_flood_incident_2026_06_09` (write-flood incident summary).
- `project_optimization_coordinator_phases123_staged` (Phase 1-3 build+ship+rollback).
- `project_inclement_arbitrage_wait_floor_gap` (OC-relevant declared-vs-effective-floor).
- `project_session_pickup_2026_07_02` (current-state confirmation: v5.7.2 shipped and live; OC ran through v5.3.0 L1 Shadow re-deploy).

### Design docs read
- `docs/QUALITY_CONTEXT.md` — Bug Class #50 (subscription rebuild), #51 (day-boundary TOU), #52 (RestoreEntity unavailable→OFF), #53 (computed-but-not-consumed). All four are relevant to OC risk surface.

### Code locations surveyed (end-to-end)
- `custom_components/universal_room_automation/domain_coordinators/optimization.py` (3974 lines — read: header, class scaffolding, `run_cycle` body, `_apply_action` chokepoint, `_persist_findings_batch`, `_dispatch_findings_updated_signal`, `_cap_findings`, `_should_skip_for_boot_storm`, `_flush_cycle_activity_summaries`, `_notify_if_severe`, shadow-accuracy validator D2d).
- `custom_components/universal_room_automation/domain_coordinators/optimization_llm.py` (header, `_extract_findings_list`, `_parse_findings` for the `findings_json`-string parsing path).
- `custom_components/universal_room_automation/database.py` — `log_findings_batch:5034`, `prune_optimization_findings:5150`, `prune_optimization_daily_digest:5326`.
- `custom_components/universal_room_automation/const.py` — `OPTIMIZER_MAX_FINDINGS_PER_CYCLE=100:1615`, `OPTIMIZER_BOOT_SETTLE_CYCLES=3:1621`, `OPTIMIZER_BOOT_STORM_ROOM_FRACTION=0.5:1626`, `OPTIMIZER_NOTIFY_DEDUP_CYCLES=12:1740`, `SCAN_INTERVAL_OPTIMIZATION=5min:1747`, `DEFAULT_OPTIMIZER_AUTONOMY_LEVEL=OPTIMIZER_LEVEL_SHADOW:1601`.
- `quality/tests/test_optimization_coordinator.py` — 14 optimizer-specific tests including `test_optimizer_cycle_one_db_write_under_boot_storm:3411`, `test_optimizer_shadow_emits_intent_no_call:649`, `test_optimizer_activity_log_shadow:1143`, LLM parser/allowlist tests, comfort-slider writeback.

### Greps run + results (REUSED / NEW)
- `OPTIMIZER_MAX_FINDINGS_PER_CYCLE`, `OPTIMIZER_BOOT_SETTLE_CYCLES`, `OPTIMIZER_BOOT_STORM_ROOM_FRACTION` — **REUSED** at `const.py:1615/1621/1626`. Fix-forward constants exist.
- `_persist_findings_batch` — **REUSED** at `optimization.py:3417` calling `database.log_findings_batch` (`database.py:5034`). Batched persistence confirmed.
- `_dispatch_findings_updated_signal` — **REUSED** at `optimization.py:3470`. One-per-cycle `SIGNAL_OPTIMIZER_FINDING_EMITTED` fire replaces the per-finding fan-out.
- `_should_skip_for_boot_storm` — **REUSED** at `optimization.py:3527`. Two triggers (uptime grace + unavailable-fraction).
- `_cap_findings` — **REUSED** at `optimization.py:3492`. META rows preserved, non-META sorted by severity and truncated to 100.
- `_flush_cycle_activity_summaries` — **REUSED** at `optimization.py:3662`. Buffers `_cycle_shadow_log_buffer` / `_cycle_clamp_log_buffer` drained to ≤2 activity rows per cycle (v5.2.2 second-channel fix).
- `OPTIMIZER_NOTIFY_DEDUP_CYCLES` — **REUSED** at `optimization.py:3599-3627`. Cross-cycle NM dedup keyed on `finding.dedup_key` for ~12 cycles.
- LLM `findings_json` string handling — **REUSED** at `optimization_llm.py:869-882`. `json.loads` under try/except; malformed JSON → whole cycle skipped (does NOT partial-commit garbage rows).
- `OPTIMIZER_LEVEL_SHADOW` chokepoint gating — **REUSED** at `optimization.py:_apply_action:2844` (single chokepoint; L1 short-circuits to `_log_activity(shadow_dry_run)` and NO `hass.services.async_call`). Tests at test file:1737-1764 assert `hass.services.calls == []` at shadow.

---

## Part 1 — Correctness Audit

### 1.1 Fix-forward verdict: LANDED

Every item on the v5.2.1 post-incident fix-forward list is present and wired:

| Fix-forward item | Verdict | Anchor |
|---|---|---|
| Batch findings persistence (1 write per cycle) | **LANDED** | `optimization.py:3417` → `database.py:5034` |
| Suppress boot-transient findings | **LANDED** | `optimization.py:3527` `_should_skip_for_boot_storm` — uptime grace (`_cycles_since_start < 3`) + boot-storm signature (>50% rooms with unavailable configured sensors) |
| Drop per-cycle sentinel flood | **PARTIALLY LANDED** | META sentinel is preserved (intentionally, for liveness) but reduced to exactly ONE per cycle; not a flood. `_cap_findings` protects the META row from truncation. |
| Throttle per-room sensors | **LANDED (upstream side)** | `_dispatch_findings_updated_signal:3470` fires SIGNAL_OPTIMIZER_FINDING_EMITTED ONCE per cycle; per-room sensors ignore payload and re-read coord state. Downstream sensor throttling is not needed given single dispatch. |
| Write-volume test | **LANDED** | `test_optimizer_cycle_one_db_write_under_boot_storm:3411` — asserts ≤2 DB writes (tier1 + LLM batch), ≤1 signal dispatch, boot-storm skip. |
| Second write channel (activity_log O(N)) | **LANDED (adversarial fix)** | `_cycle_shadow_log_buffer` / `_cycle_clamp_log_buffer` at optimization.py:530-531, drained at `_flush_cycle_activity_summaries:3662` as ≤2 rows. Buffers cleared on skip path too (:867-868). |

### 1.2 Shadow-mode actuation integrity

- Single chokepoint at `_apply_action:2844`. L1 (shadow) branches at :2948 with `veto_window=0`, fires `broker.fire_intent` (dispatcher signal only), sets `applied_outcome = OPTIMIZER_OUTCOME_SHADOW`, and returns WITHOUT `hass.services.async_call`.
- Kill-switch clamp (`_resolve_effective_level:2612`) and confidence gate (:2900) run before dispatch and short-circuit to advisory outcomes.
- Test authority: `test_optimizer_llm_shadow_no_actuation:2093-2130` and `test_optimizer_shadow_emits_intent_no_call:649` both assert `hass.services.calls == []` while confirming intent-signal emission. LLM Tier-2 flows through the SAME chokepoint (created_by tag, no bypass) — tests exercise this end-to-end.
- **Observation:** the shadow-mode invariant is well-tested at the aggregate level, but not with per-site source-mutation authority (Tier-3 discipline). Given the OC is regression-prone AND cost/comfort-adjacent (climate targets), any future move toward L2+ would need mutation-anchored tests before elevating out of shadow.

### 1.3 Lifecycle / cleanup

- `async_setup:594` registers `broker.veto_unsub` on `self._unsub_listeners` (Bug Class #50-safe).
- 5-min interval unsub also stored on `_unsub_listeners:661`.
- `async_teardown:688` stops the broker AND calls `_cancel_listeners`.
- Rate-cap deque is seeded from DB at boot (:606-652) — good restart resilience for the per-hour cap invariant.
- **Gap (LOW):** `_notify_dedup_state` (dedup TTL dict) is not cleared on teardown; benign given coordinator lifetime = HA lifetime, but grep-worthy if OC is ever spawned per-restart in a test harness.

### 1.4 Restart resilience

- Rate-cap history seeded from `get_recent_optimization_findings` (H2 fix-up).
- Boot settle gate (`_cycles_since_start < 3`) guarantees the first 15 minutes are persistence-quiet regardless of substrate state.
- Findings table has an explicit pruner (`prune_optimization_findings:5150` in database.py).
- **Gap (LOW / observability):** `_cycles_since_start` is not persisted — a mid-hour restart that occurs after grace period resets to 0 and re-imposes 15 min of grace. This is CONSERVATIVE (safe) but under-documented; call it out in operator-facing README if surfaced.

### 1.5 LLM findings_json handling

- `_extract_findings_list:867` reads structured output; new `findings_json` is a JSON string parsed with `json.loads` under `try/except (ValueError, TypeError)`.
- On invalid JSON: WARNING logged, entire cycle rejected (returns `None`). No partial-commit path.
- `_parse_findings:892` per-row: bad rows rejected with INFO, good rows kept. Severity clamped to allowlist. Confidence bounded [0, 1].
- Domain allowlist enforced via `OPTIMIZER_ALLOWED_DOMAINS_DEVICE` / `_CONFIG` and `OPTIMIZER_LLM_SERVICE_DATA_ALLOWED_KEYS`. `test_optimizer_llm_service_data_key_allowlist:2408` covers.
- **Observation:** solid; no partial-commit vulnerability visible in the parser.

### 1.6 DB write-volume discipline (per-cycle envelope)

Under steady-state Phase-1+Phase-3+LLM path:
- 1× `log_findings_batch` for Tier-1 findings.
- 1× `log_findings_batch` for LLM findings (if LLM tier ran).
- ≤2× activity summary rows (`_flush_cycle_activity_summaries`).
- 1× `SIGNAL_OPTIMIZER_FINDING_EMITTED` dispatch.
- 0× actuations at L1 shadow (default and live setting).
- NM notifications are cross-cycle-deduped for 12 cycles.

This is O(1) with respect to finding count, matching the incident postmortem's requirement.

### 1.7 Correctness findings (prioritized)

- **[MED-1] Boot-storm gate depends on `_iter_room_entries` + per-entity `_state_value` — a slow state read can prolong the cycle.** Under `_should_skip_for_boot_storm:3549-3573`, every configured sensor of every room is read synchronously. Not a persistence issue (writes are gated), but the CPU walk can compete with other coordinators at boot. Recommendation: cache the boot-storm verdict for N cycles once the gate closes, or short-circuit once a single room hits the fraction threshold. Cost of missing this: a 30-room fleet re-walks up to 5×30 = 150 state reads every 5 minutes even in steady state, only to return `(False, "")`.
- **[MED-2] Shadow-accuracy sample list is not persisted.** `_shadow_accuracy_samples` at optimization.py:563 is RAM-only; a restart resets the rolling window (default 7 days per constant). The v5.4 D2d observability signal is durable in-memory only. If shadow-accuracy is meant to gate L2 promotion, this is a blocker — the operator will restart HA weekly and never accumulate enough samples. Recommendation: either persist samples to a small DB table (`optimizer_shadow_samples`) with the same pruner discipline, or explicitly document "shadow accuracy resets on restart" in the reasoning-sensor attributes.
- **[MED-3] `_notify_dedup_state` decrement runs inside the per-finding branch.** At `_notify_if_severe:3608-3615` the TTL of ALL entries decrements on every high/critical finding call — not once per cycle. In a cycle with 10 severe findings, TTLs are decremented 10× and the ~12-cycle window collapses to ~1.2 cycles. This defeats the cross-cycle dedup for high-volume cycles. Recommendation: move decrement to a per-cycle hook (end of `_run_cycle_body`) or key TTL to `cycle_id` instead of "each notify call".
- **[LOW-1] META sentinel is inside `_cap_findings` reserved-space math (correctly), but the raw METHOD signature allows callers to pass a list already exceeding the cap.** The Tier-1 path caps once and the LLM path caps once separately, so combined `all_findings` can peak at 2× cap = 200. In steady state this is fine; in a pathological cycle where both Tiers flood, `_last_findings` retains up to 200 rows. Recommendation: apply the cap once more on the merged list before assignment to `_last_findings`.
- **[LOW-2] Rate-cap deque seed is best-effort with a bare-except that swallows readable DB failures.** Not incorrect (safety-conservative direction), but a persistent DB seed error would silently disable the invariant intended by H2. Recommendation: log at WARNING, not DEBUG, when the seed path fails at boot.

None of the above is CRITICAL. The write-flood incident class is closed.

---

## Part 2 — Livability Audit

### 2.1 Actionability of findings

Fourteen dimensions ship (Phase 1 + Phase 3 + Phase 4). The two mature ones (Comfort, Sensor Health) are actionable — bounds carried on the finding payload, shadow oracle re-reads the same producer surface. Phase-3 dimensions (`automation_responsiveness`, `energy_efficiency`, `setpoint_compliance`) are documented as deferred stubs at optimization.py:670-673 — they return `[]` until Phase 3.x. **Livability implication:** the OC advertises 14 dimensions to the operator but only ~5 emit findings in production. Silent stubs invite "why does dimension X never flag" support-load.

### 2.2 Noise level

- Cross-cycle NM dedup exists (12 cycles ≈ 1 hour) but is undermined by MED-3 above.
- META sentinel emits every cycle by design — the operator's per-cycle timeline is noisy on the OC device. Recommendation: keep META in the DB (it's the sentinels-only Review-D signal) but exclude META from the `sensor.ura_optimizer_findings` state-key display.
- Boot-storm gate correctly suppresses cold-boot floods.

### 2.3 Per-room sensor value

Per the plan, per-room `sensor.{room}_optimization_health` should carry a numeric score + degraded-dimensions attribute. Confirm whether these sensors actually surface non-META findings in the RUNNING production build (the roadmap contemplates them; live-check whether they emit real values or sentinels-only). If sentinels-only, the write-flood-fix has been so conservative it's crossed into invisibility — the classic "post-incident over-correction" pattern.

### 2.4 Operator-facing surfaces

- Autonomy level, kill switch, confidence gate, per-dimension autonomy, rate cap, quiet hours source — all exposed via `CONF_OPTIMIZER_*` in Coordinator Manager options. Good.
- Safety/security deny-list (`CONF_OPTIMIZER_SAFETY_DENY_ENTITIES`) — good.
- LLM entity selection (task + triage) — good.
- `dimension_verdicts` and `cycle_summary` on the OC reasoning sensor (v5.4 D2) — good, but `shadow_accuracy_status ∈ {warming_up, no_observable_data, ready}` is undocumented in the operator UI beyond an attribute value.

### 2.5 Path from L1 Shadow to L2+ safely

**This is the biggest livability gap.** L1→L2 promotion criteria are not codified:

- Shadow accuracy validator exists (D2d) but samples are RAM-only (MED-2) and only two dimensions are scorable (comfort, occupancy_accuracy) — the operator has no signal for the other 12 dimensions.
- There is no runbook / checklist for "when is it safe to move Comfort to L2?" — no live-canary protocol, no observation-window requirement, no rollback plan.
- The autonomy matrix (`CONF_OPTIMIZER_DIMENSION_AUTONOMY`) exists but there's no in-product guidance on WHICH dimension to promote first, HOW to observe, HOW to roll back.

### 2.6 Top livability improvements

1. **Persist shadow-accuracy samples** so the "ready" gate is meaningful across restarts (addresses MED-2).
2. **Fix cross-cycle NM dedup** (MED-3) — the intended 1-hour dedup collapses under high-severity cycles.
3. **Retire silent stub dimensions from the operator-visible surface** — either build them (Phase 3.x) or hide them from the reasoning sensor's `dimension_verdicts` map until ready.
4. **Ship an L1→L2 promotion checklist** in the coordinator design doc AND surface a `promotion_readiness` attribute per dimension on the reasoning sensor (blocked-by list: samples too few, accuracy below threshold, dimension has stub oracle, kill switch engaged, etc.).
5. **Exclude META from the display state** while keeping it in the DB.

---

## Part 3 — High-Level Plan (Prioritized Deliverables)

### Tier classification: **Tier 2-DB (three framing-disjoint reviews)**

Rationale (per CLAUDE.md standing policy):
- Regression-prone: touches the shared OC persistence + dedup primitives that a live house restart depends on.
- Cost-and-safety adjacent: findings drive climate targets; MED-2/MED-3 fixes must not weaken the shadow invariant.
- History of multi-fix-up cycles (v5.0.0/5.1.0/5.2.0/5.2.1 → rollback → v5.3.0 re-deploy). The area has earned Tier 2-DB by track record.

Framings (recommended):
- **A — correctness / edge-cases:** boot-storm gate walk cost, dedup TTL semantics, cap-of-caps on merged findings.
- **B — persistence + restart + cross-coord ripple:** shadow-sample persistence schema, migration safety of new small table, activity-log volume delta, ripple into NM.
- **C — test authority + surfaces:** per-site source mutation to prove each dedup path routes through the fixed decrement; observability sensor round-trips through RestoreEntity; sentinels-only regression guard test.

### D1: Fix cross-cycle NM dedup TTL (MED-3)

Move the TTL decrement out of `_notify_if_severe`'s per-finding path into a once-per-cycle hook at the end of `_run_cycle_body`.

**Acceptance Criteria**
- **Verify:** in a synthetic cycle emitting 10 HIGH findings sharing distinct dedup keys, each key's remaining TTL after the cycle is `OPTIMIZER_NOTIFY_DEDUP_CYCLES - 1`, not `- 10`.
- **Test:** new pytest `test_optimizer_notify_dedup_ttl_decrements_per_cycle` in `quality/tests/test_optimization_coordinator.py`.
- **Live:** on the running house, after a boot with several severe findings, `sensor.ura_optimizer_reasoning` attribute `notify_dedup_active_keys` count remains stable for ~1h before draining.

### D2: Persist shadow-accuracy samples (MED-2)

Add a small DB table `optimizer_shadow_samples(observed_at, dimension, target_id, matched)` with a pruner (mirror `prune_optimization_findings` shape). Seed `_shadow_accuracy_samples` from it at `async_setup`. Write samples in the batched persist path.

**Acceptance Criteria**
- **Verify:** after HA restart, `sensor.ura_optimizer_reasoning` reports the same `shadow_accuracy_pct` it reported just before restart (within one cycle's drift).
- **Test:** DAO round-trip test using the real schema fixture (mirrors `test_optimization_findings_dao_roundtrip:786`).
- **Live:** `shadow_accuracy_status` transitions from `warming_up` to `ready` durably; a manual restart does not reset it.

### D3: Cap the merged findings list (LOW-1)

Apply `_cap_findings` once more on `all_findings` before assignment to `_last_findings` so worst-case memory / DB row count is bounded by the single cap.

**Acceptance Criteria**
- **Verify:** pathological cycle (both tiers flood) results in `len(_last_findings) <= OPTIMIZER_MAX_FINDINGS_PER_CYCLE`.
- **Test:** new pytest exercising both-tier flood.

### D4: Boot-storm gate short-circuit + cache (MED-1)

Two-part change:
1. Short-circuit the room walk as soon as unavailable-fraction is exceeded.
2. Cache the "boot-storm cleared" verdict for K cycles so the walk doesn't re-run every 5 minutes in steady state.

**Acceptance Criteria**
- **Verify:** steady-state cycles issue at most 1 state read per room per boot-storm cache window.
- **Test:** unit test asserting call count of `_state_value` in a steady-state 30-room fleet across 3 cycles is ≤ N (K + 1) not 3×30×5.

### D5: Retire silent stub dimensions from operator surface

Remove `automation_responsiveness`, `energy_efficiency`, `setpoint_compliance` from the `dimension_verdicts` map until Phase 3.x builds them, or emit an explicit `stub` verdict token distinct from `ok`. Reasoning sensor attribute renamed accordingly.

**Acceptance Criteria**
- **Verify:** operator inspecting `sensor.ura_optimizer_reasoning` sees only dimensions that actually run.
- **Test:** assert stub dimensions are excluded from `_compute_dimension_verdicts` output (or carry the `stub` token).
- **Live:** manual attribute inspection post-restart.

### D6: L1→L2 promotion readiness attribute (livability)

Add a `promotion_readiness` attribute per scorable dimension to the reasoning sensor, exposing a small dict: `{dimension: {ready: bool, blocked_by: [reasons]}}`. Reasons include: `samples_below_min`, `accuracy_below_threshold`, `stub_oracle`, `kill_switch_engaged`, `dimension_autonomy_below_L2`.

**Acceptance Criteria**
- **Verify:** for `comfort` with no samples, `promotion_readiness.comfort.blocked_by` contains `samples_below_min`.
- **Live:** once shadow accuracy passes threshold and samples ≥ min, `ready: true` appears — this becomes the operator's checklist.

### D7: Exclude META from OC findings display state

`sensor.ura_optimizer_findings` state should reflect the latest NON-META finding; META rows stay in DB (Review-D anchor) but don't pollute the display timeline.

**Acceptance Criteria**
- **Verify:** entity state does not flip to `cycle_ok` on quiet cycles.
- **Test:** sensor unit test asserting META exclusion from state selection.

### D8: Upgrade rate-cap seed logging (LOW-2)

Log at WARNING when boot seed of the rate-cap deque fails so operators see silent invariant loss.

**Acceptance Criteria**
- **Verify:** injected DB failure produces a WARNING with the seed-failure signature; DEBUG path removed.

### Suggested build order

1. D5 + D7 (cheap, high livability, low risk).
2. D1 + D3 + D8 (bug fixes with clear tests).
3. D4 (perf polish; wants live measurement).
4. D2 (schema change — Tier 2-DB core focus; new small DAO with real-schema fixture).
5. D6 (rides on D2's data + D5's map).

### Explicit non-goals (deferred)

- Building Phase 3.x stubs. Their absence is called out in D5 rather than filled here.
- Any L2 dispatch enablement. Any move off shadow is a separate Tier-3 cycle with mutation-anchored per-site oracles and operator checkpoint (matches the standing policy).
- Inclement arbitrage-WAIT floor divergence (Appendix B of the OC plan) — belongs to the Energy Coordinator cycle, not this OC audit's scope.

---

## Falsifiable invariant (for the eventual reviewer)

**"For any cycle at `DEFAULT_OPTIMIZER_AUTONOMY_LEVEL = OPTIMIZER_LEVEL_SHADOW`, the number of `hass.services.async_call` invocations attributable to `_apply_action` is zero, AND the number of `database.log_findings_batch` calls is ≤ 2, AND the number of `SIGNAL_OPTIMIZER_FINDING_EMITTED` dispatches is ≤ 1, AND the number of `ura_activity_log` INSERTs from the OC path is ≤ 2, regardless of finding count."**

Reviewer D's job: falsify. Mutate each of `_persist_findings_batch`, `_dispatch_findings_updated_signal`, `_flush_cycle_activity_summaries`, and the shadow branch of `_apply_action` individually and confirm a specific test fails per site. Any site whose bypass leaves the suite green is an untested site.
