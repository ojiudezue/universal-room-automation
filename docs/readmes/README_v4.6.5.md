# v4.6.5 — In-Memory Anomaly Persistence (Observability Cycle)

**Date:** 2026-05-16 CDT
**Tier:** Tier 2-DB (new persist surfaces on `anomaly_log` across 4 coordinators; behavioral meta-test infrastructure; 3x parallel review framings)
**Predecessor:** v4.6.4 (polish bundle); rebased onto develop after v4.6.3.2 / v4.6.3.3 / v4.6.4 shipped.

## Why

v4.6.3 successfully migrated 10 anomaly emit sites to the canonical `save_anomaly_event()` DAO. Post-deploy, `sensor.ura_coordinator_manager_recent_anomalies` surfaced a real observability gap: HVAC, security, music_following, and the safety-detector path all have functioning `AnomalyDetector` instances that produce in-memory `_active_anomalies` entries, but those entries never reached `anomaly_log`. The unified observability surface under-reported by these 4 coordinators silently.

This cycle closes that gap by adding fresh `save_anomaly_event` emits at each coordinator's existing `record_observation` gate.

## Deliverables

### D1 — HVAC emit (`hvac.py`)
Wired `override_frequency` (mean=3.23, std=3.44 → well-shaped continuous, safe for z-score). **Suppressed** `zone_call_frequency` based on pre-deploy cardinality audit — see "Cardinality audit" below.

### D2 — Security emit (`security.py`)
Wired `alert_trigger_frequency`. Live baseline currently shows mean=1.0 std=0.1 (all observed alerts have been severity=LOW=1.0). Will fire correctly if a higher-severity alert occurs (severity=5 → z=40 → CRITICAL).

### D3 — Music Following emit (`music_following.py`)
Wired `transfer_success_rate` and `cooldown_frequency`. **Flagged for v4.6.5.1 follow-up:** live data shows mean=0.0 success rate over 1594 samples (suspicious — investigate MF stats collection), and the alert-on-improvement direction may need review.

### D4 — Safety detector audit (`safety.py`)
v4.6.5 D4 originally planned to wire `hazard_trigger_frequency`. Rebase resolved this in favor of v4.6.4 P2's deletion (audit evidence: constant 1.0 observations → z=0 → never emitted in months of production). v4.6.5 D4 was a comment-only audit; no new code. Inverted test `test_safety_detector_hazard_trigger_frequency_deleted` guards against re-introduction.

`active_hazard_count` remains wired per v4.6.3 D2 with binary-shape risk noted in code comment.

### D5 — Meta-test infrastructure (`test_v465_observability_gap.py`)
22 source-grep + behavioral tests that walk each coordinator's metric list and assert each metric is either WIRED (has `store_event` + emit code) or SUPPRESSED (in `SUPPRESSED_FROM_PERSISTENCE` with a justifying comment). Codifies the v4.6.3.1 doctrine: silent/degenerate metrics must be explicitly documented rather than silently absent.

### M2 fold-in — Orphan baseline row cleanup (`coordinator_diagnostics.py`)
`load_baselines` now filters loaded rows against the coordinator's current `metric_names` registry. Rows for deleted metrics (e.g. `hazard_trigger_frequency` after v4.6.4 P2) are skipped on load AND deleted from `metric_baselines` to keep DB hygiene. Logs the prune action so it's discoverable.

## Pre-deploy cardinality audit

Every newly-wired metric was checked against live in-memory baseline statistics on the HA instance before deploy. Same exercise that would have caught the v4.6.3.3 census_count over-emit before shipping.

| Metric | mean | std | sample_count | Decision |
|---|---|---|---|---|
| `hvac.zone_call_frequency` | 0.378 | 0.678 | 899 | **SUPPRESSED** — same shape as census_count (1825/24h); active_count=2 → z=2.39 ADVISORY would fire routinely |
| `hvac.override_frequency` | 3.234 | 3.436 | 899 | WIRED — well-shaped continuous |
| `security.alert_trigger_frequency` | 1.000 | 0.100 (floor) | 34 | WIRED — currently dead-shape (constant LOW) but correct on first higher-severity alert |
| `music_following.transfer_success_rate` | 0.000 | 0.100 (floor) | 1594 | WIRED — suspicious zero-success baseline, flagged for v4.6.5.1 |
| `music_following.cooldown_frequency` | 0.000 | 0.100 (floor) | 1593 | WIRED — directionally correct (alert on first cooldown) |
| `safety.active_hazard_count` | (event-driven, low volume) | — | — | WIRED per v4.6.3 D2 |

**zone_call_frequency suppression follows the v4.6.3.1 / v4.6.3.3 pattern exactly:** keep `record_observation` (in-memory anomaly counter on per-coordinator sensor still works), strip `store_event` + `activity_logger.log` branch, add to `SUPPRESSED_FROM_PERSISTENCE` set with citing comment, add a `_LOGGER.debug` for visibility.

## Files changed

- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — D1 (override_frequency emit + zone_call_frequency suppression with audit comment)
- `custom_components/universal_room_automation/domain_coordinators/security.py` — D2 (alert_trigger_frequency emit + handle_entry_intent → async)
- `custom_components/universal_room_automation/domain_coordinators/music_following.py` — D3 (transfer_success_rate + cooldown_frequency emits via persist helper)
- `custom_components/universal_room_automation/domain_coordinators/safety.py` — D4 audit comment merged with v4.6.4 P2 reality
- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` — M2 (orphan baseline filter + prune)
- `quality/tests/test_v465_observability_gap.py` — 22 new meta-tests (1 inverted post-rebase: hazard_trigger_frequency_deleted; 1 revised: hvac suppression instead of wiring)
- `docs/readmes/README_v4.6.5.md` — new
- `docs/BACKLOG.md` — status update + v4.6.5.1 polish entries

## Test count

- v4.6.4: 3097 passing
- **v4.6.5: 3119 passing** (+22 new v4.6.5 meta-tests, 0 regressions)
- Pre-existing 56 failures + 14 errors unchanged (test infrastructure debt)

## Deferred to v4.6.5.1

- **M3:** `_transitions_today` RestoreEntity hydration so v4.6.4 P1's `transition_count_daily` baseline doesn't skew low across restarts. Touches presence state-hydration surface — separate concern from observability persistence.
- **MF instrumentation investigation:** verify why `transfer_success_rate` baseline is 0.0 over 1594 samples (broken stats collection or genuine zero-success state?). Also reconsider whether MF metrics should alert on improvements at all.
- **Optional `hazards_per_hour` sliding-window metric:** if you actually want unusually-frequent-hazard detection (the intent of v4.6.5 D4's misguided wire-it plan), add a properly-shaped sliding-window counter. Not a regression — `active_hazard_count` already provides some signal.

## Live validation plan (Review D)

1. Post-restart, `sensor.ura_coordinator_manager_recent_anomalies.by_coordinator` should grow from current `presence=12` to include `hvac` (override_frequency), `security` (rare, conditional on alert severity), `music_following` (rare).
2. **Critical check:** `by_coordinator.hvac` should NOT spike — if zone_call_frequency suppression worked, only override_frequency contributes. Pre-deploy in-memory baseline showed 9 anomalies/day on the HVAC sensor (mix of both metrics); post-deploy that should drop to whatever override_frequency alone produces.
3. Verify `metric_baselines` DB table no longer has a `hazard_trigger_frequency` row after first URA setup_entry post-deploy (M2 fold-in should prune it on `load_baselines`).
4. Per-coordinator anomaly sensors should continue updating (in-memory tracking unaffected by suppressions).
5. No regressions in `transition_count_daily` (v4.6.4 P1) — should keep accumulating samples toward `minimum_samples=24`.

## What this is NOT

- Not v4.6.5.1 (MF instrumentation, M3 restart resilience, optional hazards_per_hour) — separate cycle.
- Not a deletion of `zone_call_frequency` — the metric stays in `HVAC_METRICS` and `record_observation` continues so the per-coordinator anomaly sensor still counts. Only the `anomaly_log` persistence path is suppressed.
- Not a DAO schema change — `anomaly_log` table is unchanged; this cycle adds emit sites, not new columns.
