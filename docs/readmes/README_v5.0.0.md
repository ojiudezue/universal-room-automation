# URA v5.0.0 — Optimization Coordinator Phase 1 (Agentic Skeleton, L1 Shadow)

> **Major version.** v5.0.0 is stage 1 of the Optimization Coordinator (the agentic skeleton). The LLM tier ships next as v5.1.0, dimension expansion as v5.2.0. The internal review doc keeps its build-cycle name (`v4.7.34_*`); the released artifact is **v5.0.0**.

**Release date:** 2026-06-09
**Tier:** Tier 2-DB (three framing-disjoint staff reviews + live validation; DB triggers fire — new `optimization_findings` table)
**Scope:** First deployable cycle of the Optimization Coordinator. Delivers the end-to-end agentic loop running at **L1 (Shadow / dry-run)** by default — the coordinator evaluates the existing substrate, emits findings with predicted effects, and scores them against actual outcomes, but performs **zero real actuation** until the operator dials the autonomy ladder up.

**Planning doc:** `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md`
**Review doc:** `docs/reviews/code-review/v4.7.34_optimization_coordinator_phase1.md`

**Trigger:** Operator directive 2026-06-08 — make URA self-optimize. Phase 1 also closes the long-standing comfort-slider orphan (the per-room ComfortTempMin/Max/HumidityMax Numbers were RAM-only with no reader; they now persist and feed the Comfort dimension).

---

## Headline Changes

- **D1** — New `OptimizationCoordinator(BaseCoordinator)` (`domain_coordinators/optimization.py`), `coordinator_id="optimization"`, `priority=5` (runs last), 5-min cycle. New "URA: Optimization Coordinator" device. Registered in `__init__.py` after HVAC + NM.
- **D2** — Six-rung autonomy ladder (L0 advisory → L1 shadow **[default]** → L2 reversible-device → L3 config+veto+±20% → L4 config-immediate+±20% → L5 unbounded) behind a single chokepoint `_apply_action`. Autonomy **matrix**: rung × per-dimension cap × confidence-gate(0.7) + rate-cap(12/hr) + quiet-hours(reuse NM) + restart-persistent kill switch. Load-bearing L2/L3 split: L2 = reversible device only; config writes require L3+.
- **D3** — `OptimizerIntentBroker` + `SIGNAL_OPTIMIZER_INTENT` / `_VETO` / `_FINDING_EMITTED`. Reuses HVAC `OverrideArrester.suppress()` TTL handshake (v4.7.33) for climate writes; thin broker generalizes to non-HVAC siblings (none subscribe in Phase 1 — additive).
- **D4** — New `optimization_findings` table (`_create_table_safe`), `log_finding` DAO (modeled on `save_anomaly_event`), `prune_optimization_findings` (30/14/7-day retention), 4 indexes.
- **D5** — Tier-1 rule engine, two dimensions: **Sensor Health** (per-room configured sensors unavailable/unknown >60s → high) and **Comfort** (per-room slider vs temp/humidity when occupied, ≥10-min sustained → medium). `cycle_ok` meta sentinel each cycle.
- **D6** — Comfort sliders (`number.py`) gain `entry.options` write-back + seed-from-options. Closes the v1-plan Appendix-A orphan.
- **D7** — Sensors: `sensor.ura_optimizer_status`, `…_findings`, `…_room_health`, per-room `sensor.{room}_optimization_health`. New `OptimizerKillSwitch` (switch, RestoreEntity + fail-closed restore) and `OptimizerAutonomyLevelSelect` (select, 6 options). NM severity {critical,high} routing.
- **D8** — Activity-log + decision-log integration for shadow / proposed / actuated / vetoed / clamped events.

## New config (CM entry options — 6 keys, 0 per-room beyond the existing comfort sliders)

`CONF_OPTIMIZER_AUTONOMY_LEVEL` (default `shadow`), `CONF_OPTIMIZER_KILL_SWITCH`, `CONF_OPTIMIZER_DIMENSION_AUTONOMY` (raw-options dict; UI selector deferred), `CONF_OPTIMIZER_CONFIDENCE_GATE` (0.7), `CONF_OPTIMIZER_RATE_CAP_PER_HOUR` (12), `CONF_OPTIMIZER_QUIET_HOURS_SOURCE` (`reuse_nm`).

## Review fix-up (Tier 2-DB, commit `5c88d9d`)

6 CRITICAL + 11 HIGH fixed in-cycle. Most important: the HVAC handshake was silently no-op (read a `hass.data` slot nothing wrote — A-CRIT-1); kill-switch/autonomy changes full-reloaded the CM entry (C-CRIT-1); kill-switch could fail open on restart (B-C2). All resolved. See review doc for the full table and the RestoreEntity cross-review adjudication.

## Known Phase-1 limitations (by design)

- At L1 (the ship default) the chokepoint `_apply_action` is not driven by live cycles — Phase-1 dimensions emit advisory findings with no `proposed_action`. The chokepoint is exercised by unit tests (incl. a synthetic-action L1-inertness test); **Phase 2 (LLM Tier-2) is the first live consumer of the actuation path.** Do not interpret a quiet dispatcher at L1 as a wiring failure.
- Per-dimension autonomy caps are operator-set via the raw options key (no UI selector yet).

---

## Live Validation (Review D) — prospective criteria, to be populated post-restart

Replace this list with a `Validated <date>` table after the restarted instance is observed (per the 2026-06-05 README-writeback rule).

- **Verify:** log line `Coordinator optimization started` present once after restart.
- **Verify:** `sensor.ura_optimizer_status.state == "healthy"` within 5 min; `autonomy_level` / `effective_level` attrs read `shadow`.
- **Verify:** `optimization_findings` table exists; within 24h `SELECT count(*),severity FROM optimization_findings GROUP BY severity` shows non-NULL severities AND at least one **non-meta** row (sentinels-only = payload shape broken).
- **Verify:** activity_log has `coordinator=optimization, action=shadow_dry_run` OR advisory rows within an hour.
- **Verify (C-CRIT-1 regression guard):** flipping `OptimizerKillSwitch` in the UI does NOT reload the CM entry — `_async_update_listener` logs the in-place/suppress line, sibling entity `last_changed` unchanged.
- **Verify:** per-room `sensor.{room}_optimization_health` populated post-first-cycle (no startup-race placeholder stuck).
- **Verify:** zero URA ERROR logs attributable to `optimization` post-boot.

| Criterion | Observed | Source |
|---|---|---|
| (TBD post-deploy) | | |
