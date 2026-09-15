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

---

## RE-REVIEW (post-rewrite, Tier-3 x2) — 2026-09-14

Both framings FIX-PLAN-FIRST; spine confirmed honest (all reuse citations re-greped, drift ≤2). All fixes applied to the rewritten plan.
- **A (reuse+invariants):** camera_census.py prior-art surface was MISSING → added (resolve_configured_cameras :570 device_id dedup, unresolved-snapshot :631/:1048, cross-platform :658). Blocklist #2 narrowed: intra-config-entry device_id grouping IS reliable+in-production (use it); only CROSS-integration joins fragile. Both invariants restated testable: (i) entity-exclusivity+group-completeness+no-drop; (ii) zero hass.services.async_call of any domain (patch-assert-zero). Citation fixes: NON_GUEST_HOSTNAME_PREFIXES (not IOT_*), UI_COORDINATORS@:34 (=OUT, :24 is COORDINATOR_EMIT_LABELS), _devices.py package-root + DEVICE_MODELS. F4 (v1c): PeakAvoidanceTracker = rate+guard reuse; per-appliance attribution is NEW.
- **B (scaffolding+build):** slice-boundary defects. v1a now owns the record schema+CONF_APPLIANCE_RECORDS(default [])+read side (metric_baselines CANNOT hold it — numeric-only, prunes non-metric rows). Observability meta-test moved to v1d (presupposes AnomalyDetector; would ship v1a RED); it's a PAIR of module constants + 4 edits. Registration AFTER energy (insertion-order setup or SPAN source empty at boot). Freshness knob named (APPLIANCE_STALE_MAX_AGE_S, appliance_const.py). enable default=True stated. strings=2 sub-sites. UI_COORDINATORS=OUT stated. Same-entity-in-two-records hole closed (reject-at-flow-validation).

Plan now build-ready for v1a. Deploy of any slice = Tier-3 operator checkpoint.

---

## v1a BUILD REVIEW (Tier 2-DB, 3 framing-disjoint) — 2026-09-14 — FIX-REQUIRED

Each framing found real defects the others missed (Tier-3 3-framing value confirmed).
- **A (correctness+invariants):** A1 HIGH no-drop leak — device_id collapse across heterogeneous roles drops 27 live entities (measured); DECISION: v1a does NO auto-merge, one record per unclaimed entity_id, grouping operator-declared only. A2 HIGH power unit-normalization bypass (Bug Class #30) — route through _units.power_state_to_w. + freshness-newest, first-not-sum power, SPAN room:None, malformed-record-blanks-census, last-wins-not-implemented.
- **B (async+lifecycle):** B-HIGH-1 sensor left polling → 50KB attrs > recorder 16KB cap every 30s (write-flood class) → _attr_should_poll=False + _unrecorded_attributes + resolve-once. Lifecycle/registration/restart/reload PASS. + double-compute, freshness restart-blind.
- **C (test authority):** C-HIGH-1 sensor wire-in anchor HOLLOW (body-mirror, M1/M2/M3 all green) + FALSE "turns RED" comments in production source → import real ApplianceCensusSensor. C-HIGH-2 commands-nothing test near-vacuous (empty fixture) → populated fixture + trap all emission surfaces. + freshness/room-key/registration untested.

Consolidated fix-up dispatched to worktree agent-a4daf81006b20b7a3. Re-verify: M1/M2/M3 must turn RED post-fix. Deploy = Tier-3 operator checkpoint (pending).
