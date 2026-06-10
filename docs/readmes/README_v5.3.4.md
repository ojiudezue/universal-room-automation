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

## Live Validation (Review D) — Validated 2026-06-10 ~18:45 UTC

| Criterion | Result | Observed evidence |
|---|---|---|
| Clean restart, no saturation | PASS | zero `did not process within 35s`; ONE isolated `held connection >120s` in the boot window (one-shot registry cleanup batch; count=1, no recurrence) — dismissed as boot transient |
| **Status-word recalibration** | **PASS** | optimizer status = **"degraded"** at house_score 55 / mode shadow — the identical live findings pile read "critical" pre-deploy |
| L1 silence | PASS | zero "Optimizer intent vetoed" lines post-restart with handshake handlers subscribed |
| Kill-list removals | PASS | `next_occupancy_in` registry matches = 0; `peak_occupancy_time` gone; 37 `next_occupancy_time` timestamp sensors remain |
| `energy_grid_demand` | PASS | `unknown` + `unconfigured_reason: grid_import_cap_disabled` (was permanently unavailable) |
| `predicted_energy_today` clamp | PASS | state 0.0, `raw_net_kwh: -23.9` |
| Forecaster regression | PASS | predicting (`away` @ 0.37 midday, model `house_state_log_freq_v1`) |
| Recorder-churn spot-check + day-after energy health | PENDING (non-blocking) | sparse-write history check + zone/room energy re-verify on 2026-06-11 |

**Operator hands-on still open (from v5.3.3, carries forward):** escalation stage→Cancel flow, Run Cycle Now debounce, options-flow label rendering (which translation shape resolved).
