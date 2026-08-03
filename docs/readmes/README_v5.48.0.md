# v5.48.0 — Overnight Incident Fixes (fan sweep trio + small fixes)

Two review cycles from the 2026-08-03 first-night-back incidents, merged.

## Fan sweep trio (the wife-reported 6AM fan shutoffs)
- **Fan-control switch restore**: HVACFanControlSwitch ported to the
  SIGNAL_HVAC_COORDINATOR_READY deferred-restore pattern — the operator's
  OFF now survives boots with a late coordinator (the 7/29 silent
  resurrection class). Behavioral tests mutation-verified.
- **Adopted fans protected**: adoption stamps the manual-off cooldown and
  external-lit fans get 2x vacancy hold (FAN_ADOPTED_VACANCY_HOLD_MULT=2.0,
  1.0=kill). The 6:47AM manual-on re-sweep class is closed; residual: an
  adopted fan in a room reading unoccupied for 10+ min still sweeps
  (home_day-trust redesign owns that, BACKLOG B-2026-08-03-4).
- **actuation_conflict memory episodes**: any HVAC fan-off dispatched
  against a live-occupied room is now episodic (observe-only; operator
  global-off excluded). The incident class is memory-visible forever.

## Overnight small fixes
- **Anomaly abs-floor**: circuit anomalies need z>=threshold AND
  |deviation|>=ANOMALY_ABS_FLOOR_W (50W; 0=kill) — kills the 3.4W
  "dryer" z=10.4 class. Breaker-trip detection verified unaffected.
- **Arriving re-arm cooldown**: after an outdoor-only ARRIVING attempt
  collapses, re-attempts from outdoor-only evidence are suppressed 15 min
  (ARRIVING_REARM_COOLDOWN_S=900; 0=kill). Arming narrowed to
  outdoor-only-evidence collapses (review MED-A1) so tracker/interior/
  camera-fired attempts never arm; bypass on interior tier1/census/
  tracker. Counters on the house-state sensor
  (arriving_rearm_suppressed/bypassed/active). Exterior-camera bypass
  deferred (plumbing > 20 LoC; narrowing removes the latency risk).
- **NM suppression visibility**: suppressed_since on NM diagnostics +
  daily WARNING while suppressed. Part (c) (restart re-confirmation)
  awaits operator decision.
- **Collateral**: test_metric_baseline_integration mock repair revived
  31 dead tests (0 revealed failures).

## Reviews
5 framing-disjoint reviews across the two branches
(docs/reviews/code-review/overnight_fixes_v5480.md): 2 HIGH (stale
incident-replay boundary; anchor-only restore tests) + 2 CRIT-class
test-authority findings (replica cooldown tests — #62 strikes six and
seven; dead-on-collection abs-floor tests) + 2 MED — all fixed;
builder AND orchestrator mutation drills red on every load-bearing line.

## Live Validation — prospective
- **Live (the restore proof):** fan_control switch is OFF at deploy;
  after the deploy restart it must STILL be OFF (first boot in 5 days
  where the operator's choice survives). Then operator/agent turns it ON
  to restore managed fans with the fixes live.
- **Live:** house-state sensor carries arriving_rearm_* attrs.
- **Live:** tonight: no occupied-bedroom fan sweeps; any conflict writes
  an actuation_conflict episode (memory status sensor).
- **Live:** no away<->arriving flap storm on outdoor-only evidence
  (suppressed counter increments instead).

### Validated 2026-08-03 (~11:10 CDT, first post-deploy boot)
| Criterion | Result | Evidence |
|---|---|---|
| Fan-control OFF survives boot | **PASS** | switch.ura_hvac_coordinator_fan_control = off post-restart — first boot since 7/29 where the operator's OFF survived (the resurrection class is closed). Then deliberately turned back ON with the adopted-fan protections live. |
| arriving_rearm_* attrs live | **PASS** | House-state sensor carries suppressed=0 / bypassed=0 / active=false. |
| Clean boot | **PASS** | House correctly home_day (real morning occupants); no URA errors. |
| No occupied-bedroom fan sweep | pending-tonight | The wife-facing criterion; first sleep cycle with fixes live. |
| actuation_conflict episodes | pending-organic | Any future occupied-room fan-off writes an episode. |
| No outdoor-only flap storm | pending-organic | Next away evening; suppressed counter is the signal. |
