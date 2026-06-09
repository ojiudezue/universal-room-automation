# URA v4.7.36 — Optimization Coordinator Phase 3 (Dimensions Expansion + Daily Digest)

**Release date:** 2026-06-09
**Tier:** Tier 2-DB (three framing-disjoint reviews; new `optimization_daily_digest` table)
**Scope:** Layers additional deterministic dimension evaluators onto the Phase-1 skeleton and adds a daily digest. All new dimensions are **advisory** (no actuation); autonomy stays L1 Shadow by default.

**Planning doc:** `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` (Phase 3)
**Review doc:** `docs/reviews/code-review/v4.7.36_optimization_coordinator_phase3_dimensions.md`
**Depends on:** v4.7.34 (Phase 1) + v4.7.35 (Phase 2).

---

## Headline Changes

- **6 new dimension evaluators** (advisory): Occupancy-Accuracy, Config-Behavior (room); Vacancy-Management, Override-Frequency (zone); State-Machine-Accuracy, Security-Posture (house). Each reads existing substrate (no new sensors, no new config) and emits findings with confidence into the same pipeline.
- **3 dimensions honestly deferred** as `[]`-returning stubs (Automation-Responsiveness, Energy-Efficiency, Setpoint-Compliance) — their substrate (per-room latency telemetry / per-room kWh attribution / compliance read-side roll-up) doesn't cleanly exist yet. No fabricated readers. Tracked for a later phase.
- **Daily digest:** new `optimization_daily_digest` table (`_create_table_safe`, `UNIQUE(date)` upsert), DAOs (`log_daily_digest`, `get_recent_daily_digests`, `prune_optimization_daily_digest`, 90-day retention), and an NM hook that rides the existing morning/evening digest cadence (no parallel scheduler). One row per local day.
- **Prune wiring fix:** both `optimization_findings` (from Phase 1) and the new digest prune are now invoked on the existing daily cleanup cadence — Phase 1 had defined the prune but never called it.
- **Sensors:** `OptimizerRoomHealthSensor` now exposes a `zones` map alongside `rooms`; zone-level findings degrade the house score and are visible per-zone.
- **Zero new CONF keys** (parsimony).

## Known limitations (by design / deferred)

- 3 dimensions deferred pending substrate (see above) — tracked for a later phase.
- Scoreboard uses uniform 15-pt-per-finding weighting (severity-agnostic). A single low-confidence advisory cannot flip a room to critical (needs 3+). Intentional simplification; severity-weighting is a future refinement.
- Config-flow translations still pending (shared follow-up with Phase 1/2).

---

## Live Validation (Review D) — prospective criteria, to be populated post-restart

- **Verify:** the 6 implemented dimensions surface correctly — force a fixture condition per dimension (e.g. an unlocked lock while AWAY → Security-Posture; a zone with high `override_count_today` → Override-Frequency) and confirm the finding + `degraded_dimensions`/`zones` attribute.
- **Verify (digest dedup):** exactly ONE row per local date in `optimization_daily_digest` even with multiple persons/digest windows (upsert on `date`).
- **Verify (date semantics):** `date` reflects the local day-of-coverage, not UTC.
- **Verify (prune wiring):** the daily cleanup runs `prune_optimization_findings` + `prune_optimization_daily_digest` (no unbounded growth).
- **Verify (sentinel resilience):** if one evaluator errors, the `cycle_ok` sentinel still emits and other dimensions still run (per-evaluator isolation).
- **Verify:** zero URA ERROR logs attributable to the new evaluators / digest hook post-boot.

| Criterion | Observed | Source |
|---|---|---|
| (TBD post-deploy) | | |
