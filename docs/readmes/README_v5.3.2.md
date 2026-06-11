# URA v5.3.2 — Routine-Awareness Next-State Forecaster

**Tier:** 2 (two framing-disjoint reviews + live validation)
**Plan:** `docs/planning/PLANNING_routine_awareness_next_state_forecaster.md`
**Review ledger:** `docs/reviews/code-review/routine_awareness_next_state_forecaster.md`
**Operator directive:** "routine awareness should ABS be fixed. It's critical." (2026-06-09)

## What was broken

`sensor.ura_presence_coordinator_next_state` (the PWA's next-state display) has
returned `unknown` / confidence 0.0 since v4.6.9 — it was a documented
`placeholder_v0` stub. Routine Awareness shipped regime-shift *detection*
(v4.6.0/v4.6.2) but never forward *prediction*.

## What shipped

New `RoutineForecaster` (`domain_coordinators/routine_forecaster.py`) mounted on
PresenceCoordinator:

- Frequency/recency model over the existing `house_state_log` — counts + dwell
  ETAs keyed by (prev_state, weekday/weekend, time-of-day bin). No new learner,
  no new tables, **zero new DB writes** (one bounded indexed read per hour,
  LIMIT 5000 newest over 60 days, deferred past the boot-settle gate).
- Prediction: most-likely next state + median ETA + support-based confidence.
  Thin data cascades to coarser cells, then returns honest `unknown`/0.0 —
  never fabricated. Guest/vacation passthrough (conf 0.3) + training exclusion.
- Vocab collapse HouseState→PWA vocab with a second-place rule so the
  prediction is never "the state you're already in".
- PWA contract unchanged (same keys; `model` = `house_state_log_freq_v1`).
- Incremental updates from `SIGNAL_HOUSE_STATE_CHANGED`; lifecycle-clean
  (#19/#50): unsubs on dedicated attrs, shutdown in teardown, re-setup guard.

Review highlights (all fixed pre-deploy): CRITICAL naive-UTC timestamps were
being re-parsed as local (every cell would have trained 5–6h off); HIGH bounded
read kept oldest rows on overflow; 4 MEDIUMs (self-loop inflation, restart
dwell, eager boot read, re-setup leak).

## Live Validation (Review D) — Validated 2026-06-10 ~02:58 UTC (~4 min post-restart)

| Criterion | Result | Observed evidence |
|---|---|---|
| Clean restart, zero URA ERRORs | PASS | system_log ERROR + URA filter: 0 entries |
| Non-unknown prediction with real model | PASS | `sensor.ura_presence_coordinator_next_state` = **home_night**, confidence **0.972**, `model=house_state_log_freq_v1`, `predicted_at_iso=2026-06-10T02:58:18Z` — first live prediction ever from this sensor |
| current_state + ETA attributes | PASS | `current_state=arriving`, `transition_eta_minutes=1` — plausible (arriving is transient; 21:58 CDT arrival → home_night) |
| Prediction ≠ current vocab | PASS | arriving (collapses to home_day) → predicted home_night |
| Boot-settle gating | PASS | `boot_settle_done=true`, released via `real_input`, presence suppressed 0 / HVAC 1; prediction appeared at settle release, not cold boot |
| No write-queue saturation | PASS | zero `did not process within` lines this boot |
| Optimizer unaffected | PASS | shadow/initializing at T+5min, no flood |
| ETA sanity day-after check | **PASS** (validated 2026-06-11 morning) | recorder history: at 21:00 CDT (house→home_night) the prediction flipped to **sleep** ~60 min before the real 22:00:34 sleep onset; at 22:00 (house→sleep) it flipped to **home_day**, matching the 06:00 wake (waking→home_day vocab-collapse working as designed); honest transient `unknown` during the thin waking cell. Full evening→morning cycle predicted correctly. |

**Boot-only transients seen and dismissed:** the recurring boot-storm websocket
client kicks (4096 pending messages) at 02:58:04–05 UTC, stopped after the
storm window — pre-existing infrastructure behavior, not URA, not v5.3.2.
