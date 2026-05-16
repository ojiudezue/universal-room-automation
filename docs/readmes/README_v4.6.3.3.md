# v4.6.3.3 — Census Count Persistence Suppression

**Date:** 2026-05-15 CDT
**Type:** Tier 1 hotfix (mirrors v4.6.3.1 pattern, different metric)
**Predecessor:** v4.6.3.2 (thread-safety hotfix)

## Problem

24 hours post-v4.6.3.2, `sensor.ura_recent_anomalies.by_coordinator.presence = 1825` over the window. After v4.6.3.1 silenced `zone_occupied_count`, the next-noisiest emit was `presence.census_count` at roughly one anomaly per minute. Same shape problem as v4.6.3.1, different metric.

## Root cause

`census_count` (number of people in the house) is a low-cardinality integer — mostly 0 during sleep/away, 1-4 when occupied. The z-score AnomalyDetector treats every census tick as a new observation. With `minimum_samples=24` and `Z_SCORE_ADVISORY=2.0`, any "person appears" tick during a mostly-empty period produces a high z-score on every observation. v4.6.3 D3's migration helpfully wired the persist path for every `record_observation` call site found in `presence.py` — but census_count, like zone_occupied_count, was structurally wrong for z-score persistence.

## Fix

Surgical, mirrors v4.6.3.1: strip the `store_event` + `activity_logger.log` branch inside the census_count anomaly handler in `presence._run_inference`. Keep `record_observation` so the in-memory `_active_anomalies` counter (driving `sensor.ura_presence_coordinator_presence_anomaly`) is unaffected.

The metric still tracks anomalies in memory; it just doesn't pollute `anomaly_log`.

After v4.6.3.1 + v4.6.3.3, **presence has zero live anomaly persistence paths**. Both source metrics are suppressed by design; both in-memory counters are preserved. Proper long-term fix (deferred): replace both with Bayesian time-bin distributions per the v4.6.2 routine-awareness shape.

## Audit findings (preserved in BACKLOG.md so they aren't lost)

Before fixing, audited every `record_observation` call site across all coordinators for the same shape risk:

| Coordinator | Metric | Shape | Disposition |
|---|---|---|---|
| presence | `census_count` | LOW cardinality int | **Fixed here** |
| presence | `zone_occupied_count` | BINARY | Already suppressed in v4.6.3.1 |
| presence | `transition_count_daily` | declared but unwired | Wire-up filed as v4.6.4 P1 |
| safety | `hazard_trigger_frequency` | constant 1.0 | Dead code — never fires (std→0 z-guard). Cleanup filed as v4.6.4 P2 |
| safety | `active_hazard_count` | LOW int, event-driven | Low volume, leave |
| security | `alert_trigger_frequency` | enum 1-5, event-driven | Low volume, leave |
| music_following | `transfer_success_rate` / `cooldown_frequency` | CONTINUOUS 0-1 | Safe |
| hvac | `zone_call_frequency` | LOW int 0-3 | **Flagged for v4.6.5** — when HVAC wires `save_anomaly_event`, this is the next-most-likely degenerate-shape candidate. v4.6.5 D5 meta-test should audit it against real cardinality before shipping. |
| hvac | `override_frequency` | growing counter | Safe |

## Files changed

- `custom_components/universal_room_automation/domain_coordinators/presence.py` — census_count anomaly branch: store_event + activity_logger.log removed (~50 LoC down to ~6 LoC debug log + 15 LoC citing comment)
- `quality/tests/test_v463_anomaly_migration.py`
  - **New:** `test_presence_census_count_persistence_suppressed` (mirrors v4.6.3.1's zone_occupancy test)
  - **Inverted:** `test_presence_uses_store_event_and_anomaly_event` → `test_presence_no_live_store_event_or_anomaly_event` (presence has no live emit path post-suppression)
  - **Inverted:** `test_presence_activity_logger_called` → `test_presence_no_activity_logger_anomaly_calls`
- `docs/BACKLOG.md` — v4.6.3.3 status, v4.6.4 polish bundle entry (transition_count_daily wire-up + hazard_trigger_frequency cleanup)

## Test count

- v4.6.3.2: 3093 passing
- **v4.6.3.3: 3094 passing** (+1 new behavioral test, 0 regressions)
- Pre-existing 56 failures + 14 errors unchanged (test infrastructure debt, separate from this cycle)

## Live validation plan

1. Post-restart, watch `sensor.ura_recent_anomalies`. `by_coordinator.presence` should drop to near-zero (both presence emit sites now suppressed).
2. Verify `sensor.ura_presence_coordinator_presence_anomaly` still updates — in-memory counter is independent of the suppression.
3. Logbook search for `action="anomaly"` + `coordinator="presence"` should be quiet.
4. No regression in other coordinator emit rates — change is scoped to presence.

## What this is NOT

- Not v4.6.5 (in-memory anomaly persistence cycle). v4.6.5 adds emits for HVAC / security / music_following / safety-detector. That branch is built (commit c4d697f) and queued for deploy after this.
- Not a complete fix for low-cardinality anomaly tracking — both presence metrics still hit `record_observation`, just not `anomaly_log`. Long-term replacement is Bayesian time-bin distributions; deferred to a future cycle.
- Not a v4.6.4 polish bundle — those items are filed but not shipping here.
