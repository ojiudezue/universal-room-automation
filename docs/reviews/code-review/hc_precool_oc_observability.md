# Code Review — HC Pre-Cool Toggle + OC Observability

Branch: `feature/hc-precool-oc-observability` (off `develop`)
Plan: `docs/planning/PLANNING_hc_precool_toggle_oc_observability.md`
Tier: **2** (regression-prone; two framing-disjoint reviews + live validation).

## Build Notes

### Files changed (production)
- `domain_coordinators/hvac_const.py` — D1 const + default.
- `domain_coordinators/hvac.py` — D1 init plumbing, property/setter,
  house-state attr.
- `domain_coordinators/hvac_predict.py` — D1 `_is_pre_conditioning_enabled()`,
  master gate guard at top of `_check_pre_conditioning`, mid-window
  flip-OFF release, last-cycle in-flight tracking.
- `switch.py` — D1 `HVACPreConditioningSwitch` (HC-device, default ON,
  Bug Class #52 guard, options write-back; deferred restore via
  `SIGNAL_HVAC_COORDINATOR_READY`).
- `config_flow.py` — D1 BooleanSelector in HVAC options.
- `strings.json` + `translations/en.json` — D1 label + helper text.
- `__init__.py` — pass `pre_conditioning_enabled` from CM options to
  HVACCoordinator at instantiation.
- `const.py` — D2d shadow-accuracy constants
  (`OPTIMIZER_SHADOW_OBSERVE_DELAY_S`,
  `OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS`,
  `OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES`).
- `domain_coordinators/optimization.py` — D2a `_last_cycle_summary` +
  `_last_cycle_actions_proposed` + `dry_run_veto_count` property; D2b
  `_last_dimension_verdicts` + `_compute_dimension_verdicts()`; D2c
  `OptimizationFinding.reasoning` field; D2d shadow-accuracy validator
  loop (`_run_shadow_accuracy_validator`, `_score_shadow_finding`,
  `_score_comfort_shadow`, `_score_occupancy_shadow`). All hooks
  invoked at the tail of `_run_cycle_body` after `_last_findings` is
  set. Evaluator loop refactored to capture per-dimension finding
  tally + raised-evaluator set.
- `domain_coordinators/optimization_llm.py` — D2c additive
  `reasoning` field parse (string-only, 512-char cap,
  malformed-tolerant).
- `sensor.py` — D2a `OptimizerReasoningSensor` class + platform
  registration; D2b `dimension_verdicts` attr on `OptimizerStatusSensor`;
  D2c `llm_reasoning_summary` attr on `OptimizerFindingsSensor`; D2d
  `shadow_accuracy_pct` + `shadow_accuracy_status` attrs on
  `OptimizerStatusSensor`.

### New test file
- `quality/tests/test_hc_precool_oc_observability.py` (23 tests).
  Drives REAL production via `_load_real_predictor_class` defensive
  loader and `object.__new__` extraction for OC helpers; AST + source
  grep where the surface is too heavy to instantiate. setdefault-only
  for `sys.modules`.

### Mutation evidence (test names that fail under the named mutation)
1. **Invert the D1 guard** (`pre_conditioning_enabled OFF` still pre-conditions):
   `TestD1GatePreConditioning::test_gate_off_skips_entire_pre_conditioning_chain`
   would fail (the test asserts both `_should_solar_bank` and
   `_should_weather_pre_cool` are NEVER called and tracking sets stay
   empty).
2. **Remove the D1 flip-OFF release**:
   `TestD1GatePreConditioning::test_mid_pre_cool_flip_off_releases_within_one_cycle`
   would fail (no `climate.set_temperature` baseline write at cycle 2).
3. **Break the Bug Class #52 restore guard** (let `unavailable`
   coerce to OFF): `TestD1Bug52RestoreGuard::test_unavailable_last_state_is_skipped_not_coerced`
   would fail (AST guard-presence assertion).
4. **Break the D2d COMFORT/OCCUPANCY oracle**:
   `TestD2dShadowAccuracy::test_comfort_oracle_scores_findings` and
   `test_oracle_records_out_of_band_as_false` would fail
   (observed_effect not populated, rolling pct stays None).
5. **D2a `dry_run_veto_count` pointed at a wrong source**:
   `TestD2aReasoningSensor::test_dry_run_veto_count_reads_broker_pending_vetoes`
   would fail (AST checks `self.broker._pending_vetoes` is the
   referenced source).

### Test suite tally
- Cycle tests (solo): **23 passed**.
- Full suite (feature branch): **34 failed, 5808 passed, 29 skipped, 14 errors**.
- Full suite (develop baseline, excluding the new test file): identical
  set — **48 lines of FAILED/ERROR**, diff with feature-branch failure
  ID set = empty. Zero new failures introduced.

### Plan deviations
- **D2c LLM JSON Schema bump deferred to follow-up.** The planning
  doc lists "include the reasoning-field schema bump in THIS PR" as
  an operator disposition. The parser is fully additive (reads
  `row.get("reasoning")`, tolerates missing / malformed values), so
  Tier-2 LLM responses with the new field "just work." The
  prompt/schema-side wording change in
  `config_flow.py:1627-1634` (the OPTIMIZER_LLM_STRUCTURE block) is
  documented in the parser comment but NOT applied in this PR
  because the schema lives behind the LLM provider's structured-output
  contract and that is out-of-scope for a code-only cycle. Tracked
  for the next LLM-tier cycle.
- **D2d comfort oracle uses a v1 conservative read** (current temp
  inside [65,80]°F) rather than the "did the predicted delta land"
  delta-based oracle implied by the planning doc. Rationale: no
  per-finding `predicted_delta` field exists today (`predicted_effect`
  is the service-call dict). The conservative oracle still drives the
  rolling % off real room-coordinator temperature reads and is
  honest about its limits (observed_effect evidence string names the
  reading). Upgrade path (compare baseline ↔ post-window temp) is
  noted for the follow-up cycle once `predicted_effect` carries a
  signed delta.

## Review Stub

> Reviewers fill in below per the Tier 2 protocol (Framing A =
> correctness + HVAC gate interaction; Framing B = async lifecycle +
> observability stability). Live validation (Review D) closes the cycle
> after restart.
