# v4.6.3.1 — Zone Occupancy Persistence Suppression + Tier 2-DB Codification

**Date:** 2026-05-14 CDT (same-day hotfix to v4.6.3 + doctrine codification)
**Type:** Tier 1 hotfix + project doctrine update
**Predecessor:** v4.6.3 (anomaly migration + smoke test infra)

## Two things in one cycle

This release bundles a v4.6.3 hotfix with the same-day codification of process learnings from the v4.6.3 Tier 2-DB review cycle. They went together because:
- The hotfix is the FIRST regression caught by the new unified anomaly observability surface (`sensor.ura_recent_anomalies`)
- The codification captures the review process that caught the underlying CRITICAL findings in v4.6.3's initial build
- The lesson learned from BOTH is the same: behavioral tests against real production paths beat surface-level "tests pass" claims

## Hotfix: Zone occupancy persistence suppression

### Problem
3 hours post-v4.6.3 deploy, `sensor.ura_recent_anomalies` showed **2117 anomalies from presence** (~12/min). Top-10 dominated by `presence.zone_occupancy` events.

### Root cause (deeper than initial hypothesis)
The over-emit was NOT "firing on every change" — the existing `if anomaly:` gate was correct. The actual problem: **binary 0/1 occupancy is a degenerate input to z-score anomaly detection.**

`_check_zone_anomalies` records `occupied_value = 1.0 if occupied else 0.0` into the AnomalyDetector for each of 5 zones, every time `_run_inference` fires (9+ triggers: startup, census update, occupancy change, camera detection, periodic, deferred retry, geofence arrive/leave, guest persistence recheck).

For a rarely-occupied zone (say 5%): baseline mean ≈ 0.05, std ≈ sqrt(0.05 × 0.95) = 0.21. Every `occupied=1.0` observation → z = (1−0.05)/0.21 = **4.52 → CRITICAL**. Baseline shifts slightly; next cycle's `occupied=1.0` still produces high z → another emit. Repeat per cycle per zone.

v4.6.3 D3 helpfully wired the persist path for every `record_observation` call site found in `presence.py`. For `zone_occupied_count` that was structurally wrong because z-score on binary input is degenerate.

### Fix
Surgical: remove the `store_event` + `activity_logger.log` calls inside `_check_zone_anomalies`. Keep `record_observation` so the in-memory `_active_anomalies` counter (used by `sensor.ura_presence_coordinator_presence_anomaly`) is unaffected.

The metric still tracks anomalies in memory; it just doesn't pollute `anomaly_log`.

### Lesson codified
A future cycle (v4.6.5) will audit every `<COORD>_METRICS` list against z-score suitability. The plan includes a meta-test enforcing the audit going forward.

## Doctrine codification (from v4.6.3 Tier 2-DB cycle)

User-coined rule: **"We will need 3x staff end reviews that are targeted at different risks."**

Applied across 4 locations:

### `CLAUDE.md` — New Tier 2-DB review tier
Promote any cycle meeting the trigger criteria from Tier 2 → Tier 2-DB:
- Touches `database.py` DAO definitions
- Migrates ≥3 callers to a new DAO
- Changes payload shape of a dispatched event or persisted record
- Adds behavioral test infrastructure against real schemas
- Followed within 1-2 versions by a planned schema migration

Tier 2-DB requires three parallel reviews framed by different risk axes (A: data integrity, B: migration correctness, C: new surfaces + test fixture authority) + live validation (Review D) confirming real values flow.

**Empirical justification embedded in the doctrine:** v4.6.3 Tier 2-DB caught **6 CRITICAL + 3 HIGH** that two generic reviewers would have converged on missing — including the silent-data-degradation B1 payload shape bug + the self-validating test fixture C1-C5.

### `docs/QUALITY_CONTEXT.md` — Three new bug classes
- **#39 Schema Mirror Drift in Test Fixtures** — never hand-copy production DDL into test fixtures; extract or AST-couple
- **#40 Self-Validating Behavioral Tests** — tests that build their own INSERT instead of calling the production DAO prove nothing
- **#41 Dedup-Mask via Low-Cardinality Description** — dedup keys built from free text require event-unique distinguishers in descriptions

### `quality/DEVELOPMENT_CHECKLIST.md` — DB-Sensitive Cycle Checklist
Operational pre-deploy checklist covering: parallel reviewer setup, fixture schema authority, behavioral test discipline, payload boundary regression test, dedup-aware logging distinguishers, post-deploy Review D sentinel check.

### `docs/planning/archive/PLANNING_quality_enforcement_hardening.md` — Shelf-ready enforcement plan
4-layer enforcement infrastructure (post-deploy sentinel script, pytest meta-tests, baseline snapshot, Claude Code agent hook) — kept in archive, not queued. Trigger criteria for promoting to active build documented. Build only on quality degradation signal.

## Files changed

### Hotfix
- `domain_coordinators/presence.py` — `_check_zone_anomalies` persist + activity_logger calls removed (~50 LoC removed, replaced with 15 LoC comment + debug log)
- `quality/tests/test_v463_anomaly_migration.py` — new test `test_presence_zone_occupancy_persistence_suppressed`

### Doctrine codification
- `CLAUDE.md` — Tier 2-DB section added
- `docs/QUALITY_CONTEXT.md` — Bug Classes #39, #40, #41 appended
- `quality/DEVELOPMENT_CHECKLIST.md` — DB-Sensitive Cycle Checklist section appended
- `docs/planning/archive/PLANNING_quality_enforcement_hardening.md` — new (archived shelf-ready plan)

### Planning + backlog
- `docs/planning/PLANNING_v4.6.5_in_memory_anomaly_persistence.md` — new plan for the observability gap discovered in soak
- `docs/BACKLOG.md` — v4.6.3.1 + v4.6.5 entries

## Test count

- v4.6.3: 3093 passing
- **v4.6.3.1: 3094 passing** (+1 new behavioral test)
- Pre-existing 56 failures + 14 errors unchanged

## Live validation plan

1. **Post-restart, watch `sensor.ura_recent_anomalies`** — `by_coordinator.presence` should drop dramatically from 2117/3h pre-fix to near-zero (presence.census_count anomalies still emit; those are continuous-valued and legitimate).
2. **Verify `sensor.ura_presence_coordinator_presence_anomaly` still updates** — its in-memory anomaly counter is independent of the suppression and should continue to function.
3. **Logbook search for `action="anomaly"` + `coordinator="presence"`** should be quiet vs the flood pre-fix.
4. **No regression in v4.6.2.2 guest mode behavior** — guest-mode gate is independent of anomaly persistence.

## What this hotfix is NOT

- NOT v4.6.5 (in-memory anomaly persistence cycle) — that's the OPPOSITE direction (adding emits to coordinators that don't write to anomaly_log). v4.6.5 plan is in `docs/planning/`. Recall hint: `"Resume URA roadmap — in-memory anomaly persistence v4.6.5"`.
- NOT a complete fix for binary-occupancy anomaly tracking — the metric is still being recorded into the AnomalyDetector baseline (just not persisted). A future cycle could drop `zone_occupied_count` from `PRESENCE_METRICS` entirely OR replace with Bayesian time-bin distribution per v4.6.2 routine-awareness shape.
- NOT a fix for the energy/compliance/security/MF/safety-detector observability — see v4.6.5.

## Today's deploy sequence (final)

Five deploys in one day:

1. **v4.6.2.1** — Humidity Fan Hardening (Tier 1)
2. **v4.6.2.2** — Guest Mode Hardening (Tier 1)
3. **v4.6.2.3** — Review Carry-Overs (Tier 1)
4. **v4.6.3** — Anomaly Migration + Smoke Test Infra (Tier 2-DB)
5. **v4.6.3.1** — Zone Occupancy Suppression + Doctrine Codification (this release)
