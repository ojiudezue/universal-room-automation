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

## Live Validation (Review D) — prospective criteria

- [ ] HA restarts clean; URA entries all load; zero new URA ERRORs.
- [ ] Within ~2 min of boot-settle release: `sensor.ura_presence_coordinator_next_state`
      shows a NON-unknown state with confidence > 0 and `model = house_state_log_freq_v1`
      (house has 60d of rich transition history; the current-state cell should have support).
      Attributes carry `current_state` + `transition_eta_minutes` (int or null).
- [ ] Prediction ≠ current state's vocab (second-place rule working).
- [ ] Log shows the deferred initial refresh firing at settle release (or first
      interval tick), NOT during cold boot.
- [ ] No new write-queue lines; recorder healthy.
- [ ] ETA sanity (day-after check): predicted transition_eta for evening→sleep
      plausibly matches household routine (~22:00 sleep onset per memory).

*Replaced with observed results post-restart per the README write-back rule.*
