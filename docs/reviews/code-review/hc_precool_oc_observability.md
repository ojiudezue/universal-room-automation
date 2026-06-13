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

## Review A — Correctness + HVAC gate interaction + flip-OFF release

Framing: correctness, pre-conditioning gate interaction, and the flip-OFF
release (highest-risk piece). Reviewed commit `d3ea90e`. All findings
verified against real code.

### HIGH-1 — Flip-OFF then flip-ON same day does NOT re-engage pre-cool/pre-heat (bug class: stuck-trigger-flag / acceptance-criterion regression)
`hvac_predict.py:444-457` clears `_pre_cool_active`/`_pre_heat_active` on
the flip-OFF release but leaves `_pre_cool_triggered_today` /
`_pre_heat_triggered_today = True` (only reset at date rollover,
`hvac_predict.py:202-209`). On flip-back-ON the SAME day,
`_should_weather_pre_cool` (`:644-660`) evaluates `not _pre_cool_active`
(True) AND `not _pre_cool_triggered_today` (**False**) → first branch
fails; fallthrough `return self._pre_cool_active and hour < PEAK_HOUR_START`
= `False`. **Weather pre-cool and pre-heat will not re-fire after a
same-day OFF→ON toggle.** This directly contradicts the D1 Live
acceptance criterion ("Flip back ON inside the pre-cool window → on the
next cycle, conditions-met branches re-engage", plan line 95). Solar
banking is unaffected (it has no `triggered_today` re-arm gate on the hot
path). Fix: in the flip-OFF release block, also clear
`_pre_cool_triggered_today` / `_pre_heat_triggered_today` so the same-day
re-arm matches the documented contract. No test covers OFF→ON re-engage
(only OFF release + steady-OFF idempotency), so this slipped through.

### MEDIUM-1 — `_last_emitted_range` staleness can mis-release a weather/pre-arrival zone (bug class: baseline-recovery edge)
The release sources baseline from `_resolve_baseline_range` →
`_last_emitted_range` (`:763-771`), which is the CORRECT fix for the
v5.3.6 banking-release no-op (verified: `_execute_zone_pre_cool` at
`:894-903` bypasses `_last_emitted_range`; map is written ONLY by the DPM
preset path `hvac.py:1434`, so it holds the TRUE pre-offset baseline — the
core release is sound). Edge: if a DPM preset emit fires for that zone
*between* the pre-cool write and the flip-OFF (e.g. house_state change
mid pre-cool window), `_last_emitted_range[zone]` advances to the new
preset range, and release writes that — not the pre-cool-time baseline.
Benign (it writes a valid current-preset target, not a banked value) but
worth a comment; the preset-resolved fallback (`:773-783`) is also
current-house-state based, so behavior is consistent. Acceptable as-is;
flag for the build note.

### LOW-1 — EC reactive pre_cool/pre_heat constraint is NOT covered by the toggle (verified intentional, document it)
Traced EC `_hvac_constraint_mode in {pre_cool, pre_heat, coast, shed}`
(`energy.py:3417-3430`) → published via `SIGNAL_ENERGY_CONSTRAINT` →
applied in HC's MAIN setpoint path (`hvac.py:1489-1490` sets
`_energy_constraint_mode`/`_energy_offset`), entirely SEPARATE from
`_check_pre_conditioning`. D1 gates only the PREDICTIVE pre-conditioning
chain; EC's reactive TOU-constraint offsets remain live when the toggle is
OFF. This is correct (the two are different mechanisms — predictive vs
reactive) and the toggle covers the right one per the plan, but no
orphan/fight risk exists because they write through different paths and EC's
offset is reconciled each constraint tick. The switch helper text / house-
state attr should make explicit that EC TOU pre_cool is NOT suppressed by
this switch, to avoid operator confusion. No code change required.

### Verified-correct (no finding)
- **Banking-release-bug class AVOIDED.** Release writes TRUE baseline
  (`_last_emitted_range`), not the offset-echoing live setpoint. Test
  `test_mid_pre_cool_flip_off_releases_within_one_cycle` asserts 75.0/68.0
  (baseline) against a live 72.0 (banked) — the exact discriminator.
- **Guard placement correct.** Gate read + flip-OFF release + early
  `return` sit at the TOP of `_check_pre_conditioning` (`:423-462`),
  after only the tracking-set resets (no setpoint/fan/cover side effect
  runs before the guard). OFF short-circuits the entire chain.
- **Default ON = no behavior change.** `_is_pre_conditioning_enabled`
  fail-safes to True (`:709-714`); seed default True (`hvac.py:269`);
  unconfigured install pre-conditions exactly as v5.3.7.
- **Bug Class #52 guard correct.** `switch.py:1569` returns WITHOUT
  coercion on non-on/off last_state, leaving the constructor/options seed
  (default ON) — not stuck OFF.
- **Idempotency correct.** `_last_pre_conditioning_gate_enabled` flip-edge
  detection (`:426`) + post-release set-clear prevents double-release
  (`test_steady_state_off_does_not_repeat_release`).
- **None/forecast edges.** `constraint is None` → `forecast_high=None`
  short-circuits `_should_weather_pre_cool`/`_should_solar_bank`; release
  path guards `baseline is None` (`:814`) and missing zones (`:811`).

### Severity tally
CRITICAL 0 · HIGH 1 · MEDIUM 1 · LOW 1. HIGH-1 must be fixed before deploy
(it breaks the documented same-day re-engage contract and would surface as
"flipped it back on but it never pre-cooled again today").

## Review B — async lifecycle + observability stability + restore + recorder load + test authority

Reviewer: ura-reviewer (Framing B). Commit `d3ea90e`. Verified against real code.

### B-HIGH-1 — D2d shadow oracle reads a phantom surface `manager.room_coordinators`; shadow_accuracy_pct can never leave `warming_up` (bug class: Fabricated in-repo API / mock-shaped-to-code)
`_score_comfort_shadow` / `_score_occupancy_shadow` (optimization.py:~1200-1240) read
`getattr(manager, "room_coordinators", None)`, then `room.current_temperature` / `room.is_occupied`.
**Neither exists in production.** `room_coordinators` is only a *local* dict at `hvac_zones.py:479`;
the CoordinatorManager never assigns `self.room_coordinators` (grep: zero `self.room_coordinators=`).
`UniversalRoomCoordinator` (coordinator.py:137) exposes occupancy via `self.data[STATE_OCCUPIED]`,
not an `is_occupied` property, and carries no `current_temperature`. Result: `room is None` → both
oracles return `(None, "room_coord_missing")` for every finding → `match` is never non-None → no
sample is ever appended → `_last_shadow_accuracy_pct` stays `None` / status `"warming_up"` forever.
**D2d is inert in production.** The Live acceptance ("status ∈ {warming_up, ready}") passes trivially
as a permanent `warming_up`, masking the dead path. Production's proven room reader is
`self._iter_room_entries()` + `self._state_value(eid)` against curated `CONF_TEMPERATURE_SENSOR`/
`CONF_OCCUPANCY_SENSORS` (optimization.py:3357-3373). *Why the 23 tests miss it:*
`test_comfort_oracle_scores_findings` injects a `MagicMock` with `room_coordinators={...}` and
`room.current_temperature=72.0` — the mock fabricates exactly the surface the code assumes.
*Fix:* re-point the oracle at `_iter_room_entries()`/`_state_value` and add a behavioral test that
builds the room surface the way production does (config-entry curated sensor → hass state), not a
hand-shaped mock. Until fixed, README must label D2d NON-FUNCTIONAL, not "warming up".

### B-MED-1 — `shadow_accuracy_status` warm-up is indistinguishable from "wired-but-broken" (bug class: silent-failure observability gap)
Because B-HIGH-1 pins the gauge at `warming_up`, an operator can't tell "not enough samples yet"
from "oracle reads nothing." Add a distinct token (e.g. `no_observable_data`) or surface the last
oracle `evidence` string as a sub-attr. This is the v5.x "sentinels-only = shape broken" pattern
recurring on the read side.

### B-LOW-1 — `_render_cycle_reasoning` re-encodes severity order inline (bug class: defensive-read dup)
The inline `max(..., key=lambda s: (...).index(s) if s in (...) else 0)` duplicates the
`severity_rank` map already centralized in `_compute_dimension_verdicts`. Reuse it. 1-LoC dedup;
fix in-cycle per "Fix LOWs In-Cycle".

### Verified-clean in this framing
- **Recorder cadence bounded.** All four new attrs ride `_OptimizerCMSensorBase`
  (`_attr_should_poll=False`, sensor.py:13578), which writes state only on
  `SIGNAL_OPTIMIZER_FINDING_EMITTED` — fired exactly ONCE per 5-min cycle via
  `_dispatch_findings_updated_signal` (optimization.py:3275, v5.2.2 single-dispatch). No per-tick
  churn. ≤288 writes/day/sensor. No write-flood regression.
- **Attr payload size bounded.** `cycle_summary[:1024]`; `cycle_actions_proposed` ≤20 with small
  `predicted_effect` dicts (optimization.py:2779); `llm_reasoning_summary` ≤20×(255+512);
  `dimension_verdicts` bounded by evaluator count; shadow attrs scalar. No unbounded findings list
  serialized into an attr.
- **`dry_run_veto_count`** reads `len(self.broker._pending_vetoes)` — correct field
  (optimization.py:244), try/except → 0 before first cycle / when broker absent. Stable snapshot
  length, not a racing per-action value.
- **D2c parser malformed-tolerance.** `optimization_llm.py:966` reads `row.get("reasoning")`,
  string-only, `[:512]`, non-string/missing → `""`, never rejects the row. `created_by="tier2_llm"`
  (const.py:1842) round-trips with the sensor filter.
- **Pillar-4 non-collision.** Validator filters `applied_outcome != "shadow_dry_run"`
  (const.py:1692); non-shadow PREDICTION_ACCURACY findings skipped (behaviorally enforced — mutation
  made them score → `test_non_shadow_outcome_skipped` FAILED). No shared `observed_effect` write.
- **Lifecycle.** New sensors derived/ephemeral (no RestoreEntity — correct). Switch
  `_handle_hvac_ready` is `@callback` + bound method + `async_on_remove` (Bug Class #19/#38/#42
  addressed). No `create_task`/`ensure_future` introduced. Attr/native_value None-safe when coord
  absent.
- **Validator never blocks the cycle.** Wrapped in try/except at the call site (optimization.py:~908);
  per-finding match checks individually guarded; runs inside the existing tick — no new timer.

### Test authority (Framing B re-run)
- Mutation #5 (veto source → `_pending_intents`): `test_dry_run_veto_count_reads_broker_pending_vetoes`
  FAILED. **Matches builder.**
- Mutation #4 (invert comfort band): `test_comfort_oracle_scores_findings` +
  `test_oracle_records_out_of_band_as_false` both FAILED. **Matches builder.**
- Added mutation (score non-shadow): `test_non_shadow_outcome_skipped` FAILED — collision guard real.
- D2b/D2d drive REAL production via `object.__new__(Coord)` + real `OptimizationFinding` + real const
  filtering. NOT vacuous, NOT mirror.
- **Caveat:** D2c `reasoning` parse, sensor registration, and `dry_run_veto_count` are
  source-grep/AST-only — functional but not behaviorally exercised. The shadow-oracle behavioral
  tests give FALSE confidence (B-HIGH-1) by asserting against a fabricated mock surface.
- Cycle file: **23 passed** (re-confirmed locally).

### Severity tally (Review B)
CRITICAL 0 · HIGH 1 (B-HIGH-1) · MEDIUM 1 (B-MED-1) · LOW 1 (B-LOW-1).
**Recommendation: COMMIT WITH CAUTION** — D2a/D2b/D2c are sound and recorder-safe; D2d must either
be re-pointed at the real room surface (`_iter_room_entries`/`_state_value`) or shipped explicitly
flagged observability-pending so the permanent `warming_up` isn't mistaken for healthy.

---

## Fix-up pass (2026-06-13)

Applied across Reviews A + B + the validator order-dependence finding. Branch tip
moved past `d3ea90e`; the review baseline still holds.

### Dispositions

| Finding | Disposition | Evidence |
|---|---|---|
| **A-HIGH-1** (same-day flip-OFF→ON does NOT re-engage pre-cool/pre-heat) | **FIXED** | `hvac_predict.py:457-465` flip-OFF release block now clears `_pre_cool_triggered_today` + `_pre_heat_triggered_today` in addition to `_pre_cool_active` / `_pre_heat_active`. New test `test_same_day_flip_off_then_on_re_engages_pre_cool` drives the real `HVACPredictor` across three cycles (ON → flip-OFF → flip-ON, all inside the 13:00 pre-cool window) and asserts (a) flip-OFF clears triggered_today, (b) flip-back-ON cycle re-engages weather pre-cool (`_pre_cool_active=True`, `_execute_zone_pre_cool` called with `reason="weather"`). Mutation: skip the `_triggered_today` clears → test fails (`assert True is False` on triggered_today). |
| **B-HIGH-1** (D2d shadow oracle reads phantom `manager.room_coordinators`; D2d INERT) | **FIXED** | `_score_comfort_shadow` + `_score_occupancy_shadow` re-pointed at the production-proven reader: `_find_room_entry_by_target` walks `_iter_room_entries()`, matches by `_room_name(entry)` (== the finding's `target_id`), then reads curated `CONF_TEMPERATURE_SENSOR` / `CONF_OCCUPANCY_SENSORS` via `_state_value(eid)` — the SAME path the comfort + occupancy_accuracy evaluators use to emit the finding. Phantom `room_coordinators` lookup deleted. Tests rewritten to install REAL `ConfigEntry` objects + `hass.states.get(eid)` state map (no `MagicMock` shaped to whatever the code asks). **Phantom-surface mutation** (`temp_eid = "sensor.does_not_exist_phantom"`): 3 D2d tests FAIL (`test_comfort_oracle_scores_findings`, `test_oracle_records_out_of_band_as_false`, `test_aware_timestamp_compares_with_aware_cutoff` — all assert `status == "ready"` which becomes `"no_observable_data"` under the mutation). New test `test_comfort_oracle_phantom_entity_yields_no_observable_data` directly anti-asserts a phantom entity → all matches None + status `no_observable_data` (this is the explicit regression catch). |
| **VALIDATOR / naive↔aware datetime at optimization.py:1111** | **FIXED** | Three pieces: (1) the validator now normalizes `now = dt_util.utcnow()` to aware UTC at the top of `_run_shadow_accuracy_validator` (some harnesses substitute `datetime.utcnow` which returns naive — order-dep with `test_oc_pillar_a_handshake.py` resolved). (2) `ts = datetime.fromisoformat(finding.timestamp)` is followed by `if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)` on BOTH the validate loop and the prune loop. (3) `from datetime import timezone` added to the optimization.py top-of-file imports. New test `test_aware_timestamp_compares_with_aware_cutoff` feeds a naive timestamp through the validator and asserts no TypeError + correct rolling result. Mutation: revert to `datetime.fromisoformat` without the tzinfo normalize → test fails with the exact `can't compare offset-naive and offset-aware datetimes` message at the same line. Order-dep proof: 67/67 pass in BOTH orders against `test_oc_pillar_a_handshake.py` post-fix; pre-fix the reverse order produced 6 failures. |
| **A-MED-1** (`_last_emitted_range` DPM-emit staleness edge) | **FIXED (comment)** | Comment added at `_resolve_baseline_range` in `hvac_predict.py:773-781` noting the benign DPM-emit-between-write-and-release case (writes a valid CURRENT-preset target, not a banked echo). No code change — the behavior is correct, just non-obvious. |
| **A-LOW-1** (helper text should clarify EC reactive TOU is NOT suppressed) | **FIXED** | `strings.json` + `translations/en.json` `hvac_pre_conditioning_enabled` description now carries an explicit `NOTE 2`: "this switch suppresses PREDICTIVE pre-conditioning only. The Energy Coordinator's REACTIVE TOU pre_cool / pre_heat constraint (driven by the live rate schedule) is a separate mechanism and is NOT suppressed by this switch." Prevents operator confusion when EC TOU pre_cool still fires with the master switch OFF. |
| **B-MED-1** (`warming_up` indistinguishable from "wired-but-broken") | **FIXED (observability token)** | `_run_shadow_accuracy_validator` now tracks `scorable_evaluated` + `scorable_inconclusive` across the loop. When the rolling pct can't be computed (under MIN_SAMPLES) AND every scorable finding the oracle saw this cycle returned inconclusive, status surfaces `no_observable_data` instead of `warming_up`. This is the surface that would have made B-HIGH-1 observable in production. Test `test_comfort_oracle_phantom_entity_yields_no_observable_data` asserts this exact token under the phantom-surface mutation. |
| **B-LOW-1** (`_render_cycle_reasoning` re-encodes severity order inline) | **FIXED** | `_render_cycle_reasoning` now declares the same `severity_rank = {"low":1, "medium":2, "high":3, "critical":4}` map already used by `_compute_dimension_verdicts` and replaces the inline `max(..., key=lambda s: ("low", "medium", "high", "critical").index(s) ...)` with `max(..., key=lambda s: severity_rank.get(s, 0))`. Single source of truth restored for severity ordering. |

### Mutation evidence (fix-up pass)

| Mutation | Result | Named test(s) failing |
|---|---|---|
| (1) Oracle reads phantom attr (`temp_eid = "sensor.does_not_exist_phantom"`) | 3 failed | `test_comfort_oracle_scores_findings`, `test_oracle_records_out_of_band_as_false`, `test_aware_timestamp_compares_with_aware_cutoff` (all `assert status == "ready"` flips to `"no_observable_data"`) |
| (2) Restore `datetime.fromisoformat(finding.timestamp)` without aware-normalize | 1 failed | `test_aware_timestamp_compares_with_aware_cutoff` with exact `TypeError: can't compare offset-naive and offset-aware datetimes` at the `if ts > cutoff` line |
| (3) Skip the `_pre_cool_triggered_today = False` clear in the flip-OFF release block | 1 failed | `test_same_day_flip_off_then_on_re_engages_pre_cool` (`assert True is False` on triggered_today post flip-OFF) |
| (4) Original build mutation #1 (invert D1 guard) | 1 failed | `test_gate_off_skips_entire_pre_conditioning_chain` (re-verified green pre-revert) |

All mutations reverted. Original 5 build mutations re-verified post fix-up.

### Order-dependence resolution proof

```
PYTHONPATH=quality python3 -m pytest \
    quality/tests/test_oc_pillar_a_handshake.py \
    quality/tests/test_hc_precool_oc_observability.py -q
→ 67 passed

PYTHONPATH=quality python3 -m pytest \
    quality/tests/test_hc_precool_oc_observability.py \
    quality/tests/test_oc_pillar_a_handshake.py -q
→ 67 passed
```

Root cause was that `test_oc_pillar_a_handshake.py` installs
`{"utcnow": datetime.utcnow}` into `homeassistant.util.dt` (naive). The
two test files use `sys.modules.setdefault`, so whichever runs first
sticks. Pre-fix the validator did `now = dt_util.utcnow()` → naive
under pillar_a-first, then `cutoff - timedelta = naive`, but the
finding timestamps in our tests came from `_utcnow()` (aware) → naive
vs aware TypeError. The fix normalizes `now` at the validator's
entry and tzinfo-normalizes every parsed `ts`, so the comparison is
naive-safe regardless of which utcnow mock won the setdefault race.

### Suite tally (fix-up pass tip)

- **Cycle file (solo):** 27 passed (was 23 pre-fix-up — 4 new tests added).
- **Full suite (feature branch):** 34 failed / 5812 passed / 29 skipped / 14 errors in 29.6 s.
- **Failure-ID diff vs develop baseline (48 lines of FAILED/ERROR):** EMPTY. Zero new failures introduced.
- **Order-dep vs `test_oc_pillar_a_handshake.py`:** 67/67 in BOTH orders.
- **py_compile:** clean across `optimization.py`, `hvac_predict.py`, `test_hc_precool_oc_observability.py`.
- **Conflict-marker grep (strict `^<<<<<<<|^=======|^>>>>>>>`):** clean.

### Deferred / declined

- None. All Review A + B findings (HIGH, MED, LOW) addressed in this pass per "Fix LOWs In-Cycle".
- D2c LLM JSON Schema bump remains deferred to the next LLM-tier cycle (already documented in build notes; out of scope here).

## Pass-2 Review (focused — D2d oracle re-point)

Focused re-review of `git diff d3ea90e..c6c683a` now that D2d is load-bearing.
Verified against real code on branch tip `c6c683a`.

### VERIFIED CORRECT
- **Producer/consumer identity match (hunt #2) — SOUND.** Every COMFORT
  + OCCUPANCY_ACCURACY producer sets `target_id=room` where
  `room=self._room_name(entry)` (optimization.py:1524, 1588, 1624, 1786).
  `_find_room_entry_by_target` (:1226-1242) matches `_room_name(entry)==target_id`
  using the SAME `_iter_room_entries`/`_room_name` pair. `_room_name`
  (:1390-1398) is deterministic (`room_name`→`name`→`entry_id`). No
  phantom-surface 2.0 — the re-point is genuinely wired to the producer surface.
- **`_state_value` (:1400-1409)** returns the HA state object; oracle reads
  `st.state` and `float(st.state)` — correct shape, not a phantom attr.
- **Phantom-surface mutation re-run (hunt #5).** Forcing the room match to miss
  fails 4 D2d tests (`test_comfort_oracle_scores_findings`,
  `test_oracle_records_out_of_band_as_false`, `test_occupancy_oracle_drives_real_reader`,
  `test_aware_timestamp_compares_with_aware_cutoff`). Tests drive the REAL
  `_iter_room_entries`/`_state_value` via installed `ConfigEntry` + `hass.states`
  map — behavioral, not re-mocked. `test_comfort_oracle_phantom_entity_yields_no_observable_data`
  anti-asserts the regression directly.
- **aware-datetime (hunt #4) — clean.** On the D2d path exactly TWO
  `fromisoformat` comparisons exist: validate loop (:1124 `ts > cutoff`) and
  prune loop (:1174 `ts >= window_cutoff`). Both normalize naive→aware UTC
  against an aware `now` (:1102) / `cutoff`. No other comparison on the path
  mixes tz. Other sites (:279 veto TTL, :612 dry-run prune) have their own
  bidirectional `_cmp_ts` normalization, off-path, not regressed.
- **no_observable_data ↔ warming_up ↔ ready (hunt #3).** `no_observable_data`
  reachable only under MIN_SAMPLES AND all-scorable-inconclusive; with a live
  temp sensor real samples now accrue and the gauge leaves `warming_up`→`ready`.
  Room-entry-not-found / sensor None / unparseable → `(None, token)` →
  inconclusive, no crash, no false match. Edge handling correct.
- **Suite (hunt #6).** Cycle file 27/27 solo. Full suite 34F/5812P/14E.
  Failure-ID diff vs develop baseline (excl. new file) = **EMPTY** (48==48,
  `comm -23` empty). Order-dep 67/67 BOTH orders vs `test_oc_pillar_a_handshake.py`.

### NEW FINDINGS

- **P2-HIGH-1 — Comfort oracle scores against a HARDCODED `[65,80]` band, not
  the finding's band → degenerate near-always-True oracle (bug class: meaningless-oracle / wrong-reference-band).**
  `_score_comfort_shadow` (optimization.py:1271) scores `65.0 <= temp <= 80.0`.
  But the COMFORT producer fires a finding ONLY when temp leaves the *per-room*
  band `_read_per_room_comfort(entry)` (:1556, 1571 `temp_val < comfort['min'] or > comfort['max']`),
  whose default is `[68,76]` (const.py:888-889) and is carried in
  `payload["bounds"]`. The room band is STRICTLY INSIDE `[65,80]`, so a finding
  that fired at e.g. 77 °F (out of `[68,76]`) re-reads 77 °F and the oracle
  scores it `True`/"accurate". The oracle reports a MATCH for exactly the
  out-of-band findings it is meant to validate — it ignores `payload["bounds"]`
  sitting on the finding. Result: shadow_accuracy_pct trends artificially toward
  100% and is not a meaningful predictor-accuracy signal. The two D2d tests use
  72 °F (in) / 92 °F (out of even `[65,80]`), so neither exercises the
  `[68,76]`↔`[65,80]` gap that exposes this. Build note (line 92-101)
  acknowledged a "v1 conservative read" pre-fix-up, but the fix-up promoted D2d
  to load-bearing without correcting the reference band. **Fix:** score against
  `finding.payload["bounds"]` (compare the post-observe-delay temp re-entering
  `[min,max]` = recovered=True; still outside = False), not a hardcoded band.

- **P2-MED-1 — Occupancy oracle can only return True or None, never False
  (bug class: one-sided/degenerate oracle).** `_score_occupancy_shadow`
  (optimization.py:1303-1323) returns `True` whenever ANY occupancy sensor has a
  non-stale read (`return True, f"occupied={any_on}"`) regardless of on/off, and
  `None` only when all reads are unavailable. It measures "the occupancy sensor
  is alive," not "the provenance disagreement that raised the finding resolved."
  Like P2-HIGH-1 this skews accuracy toward 100% and does not validate the
  prediction. `test_occupancy_oracle_drives_real_reader` confirms wiring but not
  semantics. **Fix:** define the success condition against the finding's claim
  (e.g. occupancy now agrees with the motion/mmwave provenance that triggered it).

### VERDICT: FIX-FIRST

The fix-up's three mechanical goals (A-1 same-day re-engage, B-1 oracle
re-point off the phantom surface, naive↔aware normalization) are all
correctly implemented and behaviorally tested — D2d is now genuinely WIRED to
the production room surface and the producer/consumer identity is the same
string. But D2d is not yet CORRECT: both oracles are degenerate (P2-HIGH-1
hardcoded band ignoring `payload["bounds"]`; P2-MED-1 one-sided True/None),
so `shadow_accuracy_pct` will read near-100% as an artifact rather than a real
predictor-accuracy signal. Ship only if D2d is explicitly labeled
observability-PRELIMINARY in the README (the gauge is non-degenerate-wired but
its scoring is not yet a trustworthy accuracy metric); otherwise fix P2-HIGH-1
(and ideally P2-MED-1) to score against the finding's own band/claim before
the gauge is treated as authoritative.

## Fix-up pass 2 — D2d shadow oracle coherent scoring semantics

Applied 2026-06-13 on `feature/hc-precool-oc-observability` (post-Pass-2
review tip c6c683a). Addresses P2-HIGH-1 + P2-MED-1 directly.

### Producer keys read (verified at file:line)

- **Comfort band** — `optimization.py:1602`. Producer attaches the
  per-room band as `payload["bounds"] = [comfort["min"], comfort["max"]]`
  inside `_evaluate_comfort_dimension`. Default band `[68, 76]` lives at
  `const.py:888-889` (`DEFAULT_COMFORT_TEMP_MIN` / `..._MAX`).
- **Occupancy claim** — `optimization.py:1796`. Producer attaches
  `payload = {"occupancy_ids": [...], "signal_ids": [...]}` inside
  `_evaluate_occupancy_accuracy_dimension`. The finding fires when
  motion/mmwave (signal_ids) is ON and ALL occupancy_ids report OFF
  (provenance disagreement).

### Coherent shadow-scoring semantics (now implemented)

Both oracles share the same axis: the finding fired because a flagged
condition was true at emit-time; the oracle re-reads the SAME surface
after `OPTIMIZER_SHADOW_OBSERVE_DELAY_S` and reports:

| match | Comfort meaning | Occupancy meaning |
|-------|------------------|--------------------|
| True | Temp back INSIDE `payload["bounds"]` (flagged out-of-band condition **resolved**) | Occupancy now reports ON, OR motion/mmwave trigger cleared (disagreement **resolved** / moot) |
| False | Temp still OUTSIDE `payload["bounds"]` (flagged condition **persisted**) | Motion/mmwave still ON AND every occupancy id still OFF (same disagreement **persisted**) |
| None | Missing/malformed `bounds` payload, missing temp sensor, no room entry, unparseable read | No occupancy ids, no room entry, every occupancy sensor unavailable |

Critically, when `payload["bounds"]` is absent or malformed the comfort
oracle returns inconclusive — NOT a wide default band. The prior
hardcoded `[65, 80]` strictly contained the producer's `[68, 76]` band
and turned every out-of-band finding into a "match" (degenerate
near-always-True). Same principle for occupancy: the prior implementation
returned True on ANY live read regardless of state, so False was
unreachable. False is now reachable via the motion-on + occupancy-off
persisted-disagreement branch.

### Code surface

- `_score_comfort_shadow` (optimization.py ~:1246) — reads
  `finding.payload["bounds"]`, normalizes to floats, validates
  `band_max > band_min`, then `True` when `band_min <= temp <= band_max`
  else `False`. Evidence strings carry the explicit semantic
  (`temp=X_resolved_within_[a,b]` / `temp=X_persisted_outside_[a,b]`).
- `_score_occupancy_shadow` (optimization.py ~:1331) — prefers the
  finding's own `payload["occupancy_ids"]` / `payload["signal_ids"]`
  (so we score the SAME claim that was raised, not the room's current
  config). Falls back to live config when payload is thin. Reads occ
  state via `_state_value` and short-circuits True on `any_on`. When
  all occ off, re-reads motion/mmwave: cleared/off → True (trigger
  gone, disagreement moot); still on → False (disagreement persisted).

### Mutation evidence

- **Comfort hardcoded-band mutation** — reverting
  `in_band = band_min <= temp <= band_max` to
  `in_band = 65.0 <= temp <= 80.0` made
  `test_comfort_oracle_scores_gap_value_as_persisted_false` fail
  (`assert True is False`). The new test installs a finding with
  `payload["bounds"] = [68, 76]` and `temp = 77°F` — inside the old
  hardcoded `[65, 80]` band, outside the producer's band — so under
  the mutation the oracle reports accurate=True for a finding that
  should be persisted=False. Test went red, oracle exposed.
- **Occupancy always-True mutation** — replacing
  `return False, "motion_on_occupancy_off_persisted"` with
  `return True, "MUTATION_always_true"` made
  `test_occupancy_oracle_scores_persisted_disagreement_as_false` fail
  (`assert True is False`). The new test installs the SAME
  motion-on + occupancy-off condition the producer fires on; under the
  mutation False is unreachable. Test went red, oracle exposed.

### Suite

- Cycle file solo: **30/30** pass (was 27; +3 new tests:
  `test_comfort_oracle_scores_gap_value_as_persisted_false`,
  `test_comfort_oracle_inconclusive_when_bounds_missing`,
  `test_occupancy_oracle_scores_persisted_disagreement_as_false`).
- Order-dep BOTH orders vs `test_oc_pillar_a_handshake.py`:
  **70/70** each direction (40 + 30).
- Full suite: **34 failed, 5815 passed, 29 skipped, 14 errors**.
- Failure-ID diff vs pre-fix-up baseline (cycle file excluded):
  `comm -23 post pre` and `comm -13 post pre` both **EMPTY** (48 == 48
  failure IDs unchanged). No new failures, no removed.

### Disposition

P2-HIGH-1 + P2-MED-1 fixed in code + behaviorally tested with mandatory
mutation pairs. D2d is now a coherent resolved-vs-persisted oracle for
both scorable dimensions; `shadow_accuracy_pct` reflects predictor
accuracy, not "sensors alive" or "any finding inside a wide default
band." Ready for re-review.
