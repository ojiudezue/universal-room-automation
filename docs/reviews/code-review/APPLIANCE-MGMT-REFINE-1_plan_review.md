# Plan review (x2, Tier-3 framing-disjoint) — APPLIANCE v1, 2026-09-14

Both framings returned **FIX-PLAN-FIRST**. The plan re-scopes to EXTEND, not build new.

## Framing A (completeness / feasibility / de-dup) — 2 CRITICAL
- **A-CRIT-1:** prior-art scan MISSED energy_circuits.py (SPANCircuitMonitor) + energy_billing.py.
  Already shipped: circuit discovery (energy_circuits.py:85,142), add-path CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES
  (energy_const.py:971), de-dup CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES (energy_const.py:973), controllable
  flag (energy_circuits.py:80), rename-stable unique_id (:70-77), cold-chain/tripped-breaker detect
  (:20-29,267), per-appliance z-score (:31-44), cost rate resolver energy_billing.py:29-48. -> re-scope
  v1 as EXTEND SPANCircuitMonitor + non-SPAN sources, NOT a new coordinator.
- **A-CRIT-2:** automatic cross-integration de-dup is FALSIFIED — no join key. Each device has one
  config_entry_id; 0 composite membership for the 6 integrations; MAC/model joins fail (study_a 2-way tie
  repro). -> use operator-DECLARED mapping (existing extra/exclude knobs), not an auto-resolver.
- A-HIGH-3: media_player gate 60% incomplete; `airplay` isn't a platform (it's apple_tv); 183/306 unclassified.
- A-HIGH-4: "74 entities" unreproducible (span power=50 post-skip, or 458, or 178 emporia — never 74).
- A-HIGH-5: cost model mislabeled (pro-rata not marginal); test non-discriminating; cite Envoy ids + route
  through _get_effective_rate_kwh.
- MED-6 double-emit vs existing cold-chain detector; MED-7 Emporia channels lack identity; MED-8 ThinQ
  enumeration wrong (only 2/11 have number.*_delayed_start; dishwashers read-only); MED-9 invariant hole
  (select.select_option — 67 writable circuit_priority selects); LOW-11 URA-owned collector must be BUILT
  (skeleton presence.py:7567 + key-lists sensor.py:1748-1757).

## Framing B (build-prediction / scope / scaffolding) — staging + 11 sites
- **B1:** v1 = 4 cycles. Stage v1a census(scaffold+discovery+resolver+1 sensor) / v1b categorization+onboarding
  flow / v1c energy+cost / v1d anomaly. State a falsifiable invariant for the RESOLVER and D2, not just no-actuation.
- **B2:** 11 new-coordinator scaffolding sites named (COORDINATOR_ENABLED_KEYS const.py:2455, register manager.py:388,
  DEVICE_NAMES _devices.py:36, enable switch switch.py:213, sensors under CM entry sensor.py:186, CM menu
  config_flow.py:3334, strings.json, telemetry coordinator_telemetry_const.py:24, observability meta-test
  test_v465_observability_gap.py:822, docs/Coordinator/APPLIANCE_COORDINATOR.md). CRITICAL: a coordinator is
  NOT a config entry (config_flow.py:703 aborts) — no ENTRY_TYPE_APPLIANCE.
- **B3:** D2 duplicates energy_billing.py:460-680 apportionment (double-count guard subtle). REUSE; the real
  open Q = per-appliance vs house attribution. Disclaimer "display-only, not billing-grade".
- **B4:** persistence unspecified; cumulative kWh/cost = exactly what restart wipes (B-HIGH-1/2 precedent).
- **B5:** CM-options onboarding triggers reload storm unless keys in OPTIONS_RELOAD_SUPPRESS_KEYS (__init__.py:6612).
- B7 double-alert; B8 knobs unplaced; B9 hollow D1/D2 acceptance; B11 D0 freshness half not run.

## Disposition
Both agree: re-scope to EXTEND SPANCircuitMonitor + operator-declared mapping, staged. Operator ordered a
deep coordinator-pattern + prior-art sweep (zero duplication, mature patterns only) before the rewrite.
Sweep dispatched 2026-09-14 (3 agents: pattern-maturity, reuse-map, extend-vs-new). Build NOT dispatched.
