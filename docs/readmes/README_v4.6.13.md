# URA v4.6.13 — Coordinator Telemetry Sensors (Cycle C) + v4.6.11 Recovery

**Released:** 2026-05-19
**Tier:** Tier 2-DB (user-escalated)

## Summary
Final dashboard-prep Python cycle. 21 new diagnostic sensors surfacing per-coordinator decision telemetry to the v5 Diagnostics tab. Read-only against existing tables — no schema changes.

**Plus**: this release also contains the v4.6.11 source code (`SafetyEventsSummarySensor`, 10 dashboard attribute adds across existing sensors, CM anomaly persistence wiring, three `datetime.utcnow()` → `dt_util.utcnow()` fixes). v4.6.11 was tagged on GitHub but its actual code was stranded on a feature branch — recovered here via merge.

## What ships in v4.6.13 (net new)

### New sensors (21 entities total)
- **5x `CoordinatorDecisionsTodaySensor`** — count of `ura_activity_log` rows per UI coordinator since local midnight. Signal-driven, emit-label-filtered, in-flight guard + pending queue.
- **5x `CoordinatorOverrideFrequencySensor`** — count of `compliance_log.override_detected=1` per UI coordinator over last 24h. 5-min poll.
- **5x `CoordinatorComplianceRateSensor`** — % compliance over last 7 days per UI coordinator. 30-min poll. Returns `None` (not misleading 100%) on fresh install with zero decisions.
- **1x `URADBSizeSensor`** — SQLite DB size in MB including WAL + SHM sidecars.
- **5x `CoordinatorLastDecisionSensor`** — timestamp + context of most recent activity_log row per UI coordinator. `device_class=TIMESTAMP`.

### UI→emit mapping
- `presence` → `(presence, transit, room)` — transit + room emits roll up under presence per dashboard plan.
- `hvac` → `(hvac,)`, `energy` → `(energy,)`, `safety` → `(safety,)`, `security` → `(security,)`.
- `compliance` and `notification` meta-emits explicitly NOT mapped (would double-count).

Lives in `domain_coordinators/coordinator_telemetry_const.py` — one-file change to revise.

## v4.6.11 recovery (also in this release)

PR #310 for v4.6.11 merged only planning docs into master; the build commit + review fixes + version stamps were stranded on `feature/v4.6.11-d3-persistence-and-attrs`. Recovery merge `1ac52e7` brought them into this release.

**v4.6.11 content now landing for the first time on master:**
- D1: CM anomaly persistence wiring (`load_baselines` on `async_start`, `save_baselines` after observation, `store_event` dispatch)
- D2: Three `datetime.utcnow()` → `dt_util.utcnow()` fixes in `coordinator_diagnostics.py`
- D4: 10 dashboard attribute adds across existing sensors
- New `SafetyEventsSummarySensor` entity

See `docs/reviews/code-review/v4.6.11_d3_persistence_and_attrs.md`. Memory rule `feedback_deploy_pr_diff_verification.md` filed to prevent recurrence.

## Review ceremony (v4.6.13)
3x parallel Tier 2-DB reviewers. **0 CRITICAL + 0 HIGH + 4 MEDIUM + 4 LOW.** Two MEDIUM fixed (D2/D3 db-ready fallback, UI_COORDINATORS const usage). One MEDIUM declined (A.L1 would regress to v4.6.3.1 thread-safety bug). See `docs/reviews/code-review/v4.6.13_coordinator_telemetry.md`.

## Tests
- 47/47 v4.6.13 tests pass
- v4.6.11 + v4.6.12 regression suites clean
- Full suite: 3408 passed / 57 failed / 14 errors / 2 skipped — same pre-existing baseline, 0 regressions

## Live-validation acceptance
Post-restart, via `python3 scripts/post_restart_validation.py all`.

## What's next
- **Dashboard v5.0 D3-D7** — wire all 10 tabs against Cycle A+B+C sensors
- **Telemetry layer documentation** (per user ask post-cycle)
