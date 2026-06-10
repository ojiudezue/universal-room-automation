# URA v5.3.4 — OC Pillar A Handshake + Kill-List + B4 Live-Health

Combined release of three reviewed cycles (one restart):

1. **OC Phase 5 Pillar A — sibling handshake** (Tier 2-DB: 3 reviews + 4th pass; 1 CRITICAL + 4 HIGH + 6 MEDIUM fixed). Ledger: `docs/reviews/code-review/oc_pillar_a_handshake.md`
2. **Prediction-sensor kill-list** (Tier 2; 1 HIGH + 2 MEDIUM fixed). Ledger: `docs/reviews/code-review/prediction_sensor_kill_list.md`
3. **B4 live-health repairs** (Tier 2; 2 HIGH + 3 MEDIUM fixed). Ledger: `docs/reviews/code-review/b4_live_health_repairs.md`

## What ships

### Pillar A (inert at L1 — wiring for the day the operator dials L2+)
- `honor_optimizer_intent()` on Energy/Presence/Security with safe-default vetoes: EVSE switch+breaker during off-peak windows or active load-shed, shed/drain-controlled plugs (any TOU period, fail-closed on degraded TOU), battery-strategy writeables (resolved fresh), presence input sensors, locks + alarm panels, observation_mode blanket (NOTE: any sibling's observation_mode vetoes all optimizer actuation house-wide — by design).
- The veto loop actually BLOCKS now (review CRITICAL: vetoes were previously purged unread after the action ran).
- L1 stays byte-silent: handlers no-op at advisory/shadow; zero added hot-path work.
- **Operator-requested status recalibration:** optimizer status "critical" now requires an actual critical-severity finding; HIGH piles read "degraded".

### Kill-list
- `peak_occupancy_time` + `next_occupancy_in` sensors removed (~37 rooms each) with one-shot registry cleanup; `next_occupancy_time` refit to `device_class=timestamp` (client-side countdown) with change-only writes — **~50k recorder writes/day eliminated**; confidence attr fixed (was "8000%").

### B4 live-health
- `energy_grid_demand`: unavailable→unknown with `unconfigured_reason` (was permanently dead behind a never-enabled option gate).
- `predicted_energy_today/week/month`: clamped ≥0 with signed `raw_net_kwh` attr (net-of-solar underflow); cost stays signed (export credit).
- Occupancy-weighted switch persistence verified sound + locked with production-path round-trip tests.

## Live Validation (Review D) — prospective criteria
- [ ] Clean restart; zero new URA ERRORs; no write-queue saturation.
- [ ] Optimizer status reads **"degraded"** (not "critical") with the current 5 HIGH dead-sensor findings; flips healthy if the operator revives Garage B/Jaya devices.
- [ ] L1 silence: no "Optimizer intent vetoed" INFO lines in logs over one full cycle.
- [ ] `sensor.<room>_next_occupancy_time` shows a tz-aware timestamp with sane confidence %; `next_occupancy_in` + `peak_occupancy_time` entities GONE from the registry (~74 removals logged once).
- [ ] Recorder churn: spot-check that next_occupancy_time writes only on prediction changes (recorder history shows sparse writes vs the old per-minute stream).
- [ ] `energy_grid_demand` = unknown with `unconfigured_reason` attr (not unavailable).
- [ ] `predicted_energy_today` ≥ 0 with `raw_net_kwh` attr carrying the signed value.
- [ ] Day-after: zone/room energy and forecaster remain healthy (no regression from the merge).

*Replaced with observed results post-restart per the README write-back rule.*
