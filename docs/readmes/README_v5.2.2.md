# URA v5.2.2 — Optimization Coordinator write-queue saturation fix (incident remediation)

**Release date:** 2026-06-09
**Tier:** Tier 2-DB remediation — fixes the root cause of the 2026-06-09 production incident.
**Trigger:** v5.0.0–v5.2.1 (deployed staged this morning) caused a **DB write-queue saturation** that starved core URA writes (`environmental data` / `census snapshot` timed out at 35s; a caller held the DB connection >120s). After an operator UI parent-reload (the watchdog-hazard path), core setup was cancelled and the supervisor restarted HA. **Rolled back to v4.7.33 to stabilize.** This release fixes the root cause so the optimizer can be re-deployed for live testing.

## Root cause
The cycle persisted findings **one at a time** (`optimization.py` per-finding loop): each finding did its own `log_finding` DB write **and** its own `SIGNAL_OPTIMIZER_FINDING_EMITTED` dispatch (→ ~35 per-room `optimization_health` sensors re-read). The **Sensor-Health dimension fires one finding per room with unavailable sensors** — during HA's boot-storm, 20–35 rooms are unavailable, so each cycle dumped dozens of individual writes into URA's single shared write queue (saturating it) and dozens of signal dispatches (websocket "4096 pending messages" backpressure). Cost was **O(N findings)** per cycle.

## Fix — per-cycle cost is now a small constant, regardless of finding count
- **Batched persistence:** new `database.log_findings_batch()` writes all findings in **one transaction** (one connection acquisition, one `executemany`, one commit; per-row None-guards skip bad rows without failing the batch). The cycle calls it **once** for the Tier-1 set and **once** for the LLM set → ≤2 DB writes/cycle to `optimization_findings`, not N. The legacy per-finding `_persist_finding` is removed from the cycle path (kept as a back-compat shim).
- **Single signal dispatch:** `_dispatch_findings_updated_signal()` fires `SIGNAL_OPTIMIZER_FINDING_EMITTED` **once per cycle** (after persistence) instead of per finding. Sensors re-read once.
- **`_consider_apply` audited:** no per-finding `optimization_findings` write (at L1 Shadow, `proposed_action=None` short-circuits to advisory-only; outcomes are recorded on the finding object and captured in the batched write).
- **Boot-storm settle gate:** `_should_skip_for_boot_storm()` — when uptime grace hasn't elapsed (first cycle) OR a large fraction of rooms have unavailable sensors (the boot-storm signature), the cycle persists only the META sentinel and skips the dispatch. Logged at INFO.
- **Per-cycle findings cap:** `OPTIMIZER_MAX_FINDINGS_PER_CYCLE = 100` — pathological cycles are truncated (highest-severity first, META preserved) with a WARNING.
- **SECOND channel (found in adversarial review):** `_consider_apply`'s `shadow_dry_run` / below-gate-clamp branches were writing `ura_activity_log` + dispatching `SIGNAL_ACTIVITY_LOGGED` **per finding** — an equal-sized O(N) flood through a *different* table that the batching fix alone missed. Now buffered per-cycle and emitted as **≤2 summary rows** (one shadow summary + one clamp summary). The boot-storm skip path no longer runs the per-finding activity loop either.
- **Boot-settle grace raised** `OPTIMIZER_BOOT_SETTLE_CYCLES` 1 → 3 (slow cloud-device boots take several cycles).
- **The regression test now gates BOTH channels:** `test_optimizer_cycle_one_db_write_under_boot_storm` asserts `log_finding.call_count == 0`, `log_findings_batch ≤ 2`, `log_activity ≤ 2`, and signal dispatch ≤ 1 — under a 35-unavailable-room cycle. This is the write-volume gate the original pre-deploy review lacked.

## Validation
- New regression test **`test_optimizer_cycle_one_db_write_under_boot_storm`** — drives a real cycle with 35 unavailable rooms and asserts ≤2 `log_findings_batch` calls, **zero** per-row `log_finding` calls, and ≤1 signal dispatch. This test **fails against the v5.2.1 code** (would see 36+ writes + 36+ dispatches) and passes after the fix. Plus batch-DAO roundtrip, boot-storm-skip, uptime-grace, and cap tests.
- 90/90 optimizer tests pass; full suite 5377 passed / 44 failed / 14 errors (baseline parity).

## Live Validation (Review D) — the critical post-deploy check
- **PRIMARY:** after restart + several optimizer cycles (incl. the boot-storm window), the log shows **ZERO** `DB write worker did not process request within 35s` and **ZERO** `DB write caller held connection >120s`. (This is the incident signature — its absence is the proof.)
- **Verify:** `optimization_findings` still gains rows (batched), and the per-room `optimization_health` sensors update once per cycle (no websocket "4096 pending messages" burst from the optimizer).
- **Verify:** core URA writes (environmental data / census) no longer time out.
- **Verify:** optimizer status `healthy`, `mode=shadow`; no `optimization`/`optimization_llm` errors.

| Criterion | Observed | Source |
|---|---|---|
| (TBD post-deploy) | | |
