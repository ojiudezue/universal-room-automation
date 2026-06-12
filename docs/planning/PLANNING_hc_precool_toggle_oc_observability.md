# Planning — HC Pre-Cool/Pre-Heat Master Toggle + OC Observability Enrichment

**Branch base:** `develop` (v5.3.7 LIVE) · **Status:** PLAN ONLY
**Operator-approved scope (2026-06-11 pruned menu):** ONE HC toggle + 4 additive OC observability deliverables (D2a Reasoning sensor, D2b per-dimension verdicts attr, D2c llm_reasoning_summary attr, D2d shadow_accuracy_pct attr). Nothing else.

---

## Institutional Context Verified

### Surfaces grepped + verdicts

| Proposed | Verdict | Evidence |
|---|---|---|
| **HC pre-cool/pre-heat master toggle (switch)** | **NEW** (no existing pre-conditioning gate) | `CONF_HVAC_*` grep over `domain_coordinators/hvac_const.py` returns `CONF_HVAC_SOLAR_BANK_ENABLED` (v6.x trigger sibling), `CONF_HVAC_SOLAR_BANK_FLOOR`, `CONF_HVAC_SOLAR_BANK_SOC_MIN`, `CONF_HVAC_PRECOOL_FORECAST_HIGH` (a *threshold*, not an enable/disable). `_check_pre_conditioning` (`hvac_predict.py:344`) has NO master enable gate — `zone_intelligence_enabled` only gates SOLAR + PRE-ARRIVAL + PRE-HEAT (line 394). Weather pre-cool runs unconditionally. Operator-confirmed: nothing equivalent exists. |
| **Switch on HC device (default ON)** | **REUSED PATTERN** | Mirror `ECSolarBankingSwitch` (`switch.py:855`) — but the HC equivalent must register on the **HVAC Coordinator** device, not EC. The factory `_ec_switch_factory` is EC-bound (reads `manager.coordinators.get("energy")`, `SIGNAL_ENERGY_COORDINATOR_READY`). No HC-bound equivalent factory exists — needs a parallel `_hc_switch_factory` OR a bespoke `HVACPreConditioningSwitch` mirroring `HVACDynamicPresetSwitch` (which already lives on the HC device + has Bug Class #52 guard, `switch.py:1381`). **Decision: bespoke class mirroring HVACDynamicPresetSwitch** — single-purpose, only one switch needs HC residency this cycle; factory generalization would be premature. |
| **Bug Class #52 restore-skip guard** | **REUSED** | Canonical pattern at `switch.py:1381,1509,1645,1786,1921,2737,3539` — copy verbatim. |
| **v5.3.7 dynamic restore-accounting registration** | **NOT APPLICABLE** | `_register_for_restore_accounting` (`switch.py:597,1081`) is EC-specific (sub_switches_synced sensor). HC has no analog. The HC switch does NOT participate in EC's restore-accounting counter; the v5.3.7 "dynamic registration" rationale doesn't apply. (Reviewer: confirm this in framing B.) |
| **Gate read pattern** | **REUSED** | `_is_solar_banking_enabled()` (`hvac_predict.py:599`) — read attr off HC via coordinator_manager; fail-safe to True (preserve current behavior). HC equivalent reads `manager.coordinators.get("hvac")` not "energy". |
| **`banking_enabled` attr precedent (distinguish operator-OFF from conditions-unmet)** | **REUSED PATTERN** | `hvac.py:2160-2169` — new `pre_conditioning_enabled` attr beside existing `pre_conditioning_zones` / `solar_banking_zones` on the same house-state sensor. |
| **OC Reasoning sensor (D2a)** | **NEW** | Grep of `sensor.py` for "OptimizerReasoning" / "reasoning_summary" / "OptimizerDimensionSensor" / "shadow_accuracy" → zero matches. Existing OC sensors: `OptimizerStatusSensor` (13626), `OptimizerFindingsSensor` (13822), `OptimizerRoomHealthSensor` (13884), `RoomOptimizationHealthSensor` (13917). None surface plain-English reasoning. |
| **Per-dimension verdicts (D2b)** | **NEW attribute on existing sensor** (parsimony) | `_zone_scores` already exists (`optimization.py:544`) and is surfaced under `zones` attr of `OptimizerRoomHealthSensor` (13913). `_dimension_scores` does NOT exist yet — the cycle iterates evaluators but does not score per-dimension. Attach the new attr to **OptimizerStatusSensor** (one glance entity per operator's hierarchy). |
| **`llm_reasoning_summary` (D2c)** | **NEW attribute** | `optimization_llm.py:869-882` shows the v5.2.1 fix: structured output is `findings_json: str` (JSON array of findings). Each finding row has its own fields parsed at `optimization_llm.py:914-948` (dimension/severity/confidence/target_level/target_id). There is currently NO captured top-level reasoning prose — the LLM only emits structured rows. **Decision: capture the LLM's per-row `description` strings for the most recent cycle's LLM findings + (NEW) a `reasoning` optional row field (additive — opt-in, malformed-tolerant) parsed into the same attr.** The schema is extended at the parser level; rows without `reasoning` keep working. Surfaced on `OptimizerFindingsSensor`. |
| **`shadow_accuracy_pct` (D2d)** | **NEW attribute + NEW lightweight validator** | `predicted_effect: dict \| None` and `observed_effect: dict \| None` already exist on `OptimizationFinding` (`optimization.py:204-205`). `predicted_effect` IS populated in `_consider_apply` shadow + L2 dispatch branches (`optimization.py:2397, 2803`). `observed_effect` is referenced only in the read-side at `sensor.py:13865-13873` ("the Phase-4 prediction-vs-actual score for the most recent applied finding") — but **no producer populates it today**. A small validator loop must populate `observed_effect` for shadow-mode findings before the rolling % is meaningful. Surface on `OptimizerStatusSensor`. |
| **OC veto polls (dry-run veto count)** | **REUSED** | Broker stores `_pending_vetoes: dict[action_id → (deadline_utc, vetoed_by)]` (`optimization.py:244`). Already counted internally; surface the rolling count alongside reasoning. No new infra. |

### Prior planning docs consulted
- `docs/planning/PLANNING_solar_banking_toggle.md` — pattern template for D1 (sibling cycle); includes the "release path" trap (FALSIFIED twice) that the HC toggle does NOT inherit because pre-conditioning has natural cycle boundaries (peak start / off-peak end) where the active flags clear themselves (`hvac_predict.py:389-391, 537-539`). No mid-bank-style baseline restoration is needed — see "Open Q1" below.
- `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR.md` — Three Pillars architecture (Health / Prediction-Validation / Goal-Driven). v5.3.0 shipped Pillar 2 (Prediction-Validation) reading existing Bayesian surfaces; the new shadow_accuracy_pct is a SEPARATE concept (predicted vs observed effect of OC's own decisions), not the Bayesian-vs-actual pillar. Note this distinction in framing C of review.
- `docs/planning/PLANNING_ec_envoy_boot_decoupling.md` — source of the v5.3.7 Bug Class #52 + dynamic-counter pattern; consulted for the restore guards on the new HC switch.

### Code locations surveyed (end-to-end)
- `domain_coordinators/hvac_predict.py:344-540` — `_check_pre_conditioning` (the gate site).
- `domain_coordinators/hvac_predict.py:599-619` — `_is_solar_banking_enabled` (the gate-read pattern to mirror).
- `domain_coordinators/hvac.py:2150-2170` — house-state sensor attrs (where `pre_conditioning_enabled` will be added).
- `switch.py:597-807` — `_ec_switch_factory` (NOT reused; pattern reference only).
- `switch.py:1381,1509,1645,1786,1921,2737,3539` — Bug Class #52 skip pattern (canonical).
- `switch.py:1300-1700` — `HVACDynamicPresetSwitch` (HC-resident switch reference impl).
- `domain_coordinators/optimization.py:683-867` — `run_cycle` (where dimension-verdict aggregation hooks in).
- `domain_coordinators/optimization.py:189-210` — `OptimizationFinding` dataclass (predicted_effect / observed_effect slots).
- `domain_coordinators/optimization.py:2380-2418` — shadow-path predicted_effect population.
- `domain_coordinators/optimization_llm.py:857-948` — LLM findings_json parsing (D2c hook).
- `sensor.py:13552-13915` — all four existing OC sensors.

### Memory bodies pulled
- `feedback_parsimonious_room_config.md` — ONE HC toggle, additive attrs over new entities. Reaffirmed mid-scope (operator: "ONE HC toggle, attrs over new entities where an OC sensor already exists").
- `feedback_no_fabrication_dhcp_incident.md` — confirmed `findings_json` shape from code, not memory.
- `feedback_db_sensitive_3x_targeted_reviews.md` + `feedback_tier2db_for_regression_prone.md` — framing guidance for the review tier.

### Design docs read
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — confirmed HC owns the pre-conditioning lifecycle; toggle residency is correct on HC device.
- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` — confirmed OC is "L1 Shadow currently"; the shadow_accuracy work feeds the documented L1→L2 promotion decision.

---

## Tier classification

**Tier 2 (regression-prone, two framing-disjoint reviews) + live validation.**

Justification:
- D1 touches HVAC pre-conditioning decision logic (regression risk: silently disable weather pre-cool / solar banking gate interaction / pre-heat). Cross-coordinator ripple: HC ↔ EC (the solar banking sibling toggle lives on EC and reads net_power; both gates must be independently composable — operator OFF on banking + OPERATOR OFF on pre-conditioning must each do exactly what the label says, with no surprise interaction).
- D2a–D2d are additive observability on an existing coordinator and existing sensors. Recorder bloat is the only failure mode; bounded by attr stability rules below.
- Not Tier 2-DB: no DAO change, no payload-shape change, no schema migration. Standing-policy escalation NOT warranted — this is regression-prone-bounded, not trust-hierarchy-ripple.

### Proposed review framings (disjoint)
- **Review A — Correctness + HVAC gate interaction.** Verify D1 gate composes correctly with the existing `zone_intelligence_enabled` and `_is_solar_banking_enabled` gates (truth table); weather pre-cool, solar banking, pre-arrival, pre-heat each behave per label when toggle = OFF; `pre_cool_active` / `pre_heat_active` flag lifecycle is correct on flip + restart; Bug Class #52 + #5 guards present; no new fabrication of HA APIs.
- **Review B — Async lifecycle + observability stability.** Sensor attr churn bounded; OC cycle reentrancy guard not broken by new attr computation; restore semantics on the new HC switch (first-install seed path, options-write-back vs RestoreEntity precedence — sibling-EC semantics may NOT apply on HC, verify); the shadow_accuracy validator loop never blocks the cycle; LLM `reasoning` row-field is malformed-tolerant; no untracked background tasks.

---

## Deliverables

### D1 — HC Pre-Conditioning Master Toggle (switch on HC device, default ON)

A single switch on the URA HVAC Coordinator device that enables/disables ALL of `_check_pre_conditioning`'s predictive pre-conditioning branches (weather pre-cool + solar banking + pre-arrival + pre-heat). Solar HVAC Banking master toggle (EC) remains the finer-grained gate for the banking branch specifically — D1 is the parent gate; if OFF, the EC banking gate's state is irrelevant.

**Files changed:**
- `domain_coordinators/hvac_const.py` — `CONF_HVAC_PRE_CONDITIONING_ENABLED` (`"hvac_pre_conditioning_enabled"`), `DEFAULT_HVAC_PRE_CONDITIONING_ENABLED = True`.
- `domain_coordinators/hvac.py` — `pre_conditioning_enabled: bool` attr on `HVACCoordinator` (seeded from options on `__init__`, settable by the switch); new `pre_conditioning_enabled` attr emitted on the house-state sensor (lines ~2160) beside `pre_conditioning_zones`.
- `domain_coordinators/hvac_predict.py` — `_is_pre_conditioning_enabled()` (mirrors `_is_solar_banking_enabled`); guard at the TOP of `_check_pre_conditioning` (after `pre_arrival_zones = pre_arrival_zones or set()`, before the per-feature dispatches). When OFF: clear `_pre_conditioning_zones`, do NOT toggle `_pre_cool_active` / `_pre_heat_active` flags (they self-clear at peak/off-peak boundaries; flipping them mid-window would cause a stuck-state on flip-back).
- `switch.py` — `HVACPreConditioningSwitch` mirroring `HVACDynamicPresetSwitch`: HC device residency, default ON, Bug Class #52 skip when last_state not in (`on`,`off`), options-write-back on toggle (sole source of truth), `available` = HC registered.
- `config_flow.py` — BooleanSelector in the HVAC options step (default `True`); helper text explicit that the switch is authoritative at runtime (sibling-CM-EC semantics).
- `__init__.py` — wire options→`pre_conditioning_enabled` setter on entry-options reload (mirror existing `_CONF_HVAC_SOLAR_BANK_*` plumbing at lines 4027+).
- `strings.json` + `translations/en.json` — switch name "HVAC Pre-Conditioning", description.

**Constants (NEW):** `CONF_HVAC_PRE_CONDITIONING_ENABLED`, `DEFAULT_HVAC_PRE_CONDITIONING_ENABLED = True`.

**Acceptance Criteria:**
- **Verify:** With switch OFF, none of `_pre_conditioning_zones`, `_solar_banking_zones`, `_pre_cool_active=True`, `_pre_heat_active=True` get newly set within one cycle. Existing active flags self-clear naturally at peak/off-peak boundaries.
- **Verify:** With switch ON (default), behavior is byte-identical to v5.3.7 — both regression suites pass.
- **Verify:** Toggle interaction matrix — Pre-Conditioning OFF + Solar Banking ON → no banking; Pre-Conditioning ON + Solar Banking OFF → banking suppressed but weather pre-cool/pre-heat/pre-arrival still run; Pre-Conditioning OFF + Solar Banking OFF → all off; ON+ON → all conditional on substrate.
- **Verify (restart resilience):** Restart with toggle OFF → switch restores OFF; pre-conditioning stays off across the boot.
- **Verify (Bug Class #52):** Restart with last_state=`unavailable` → switch falls back to the options/constructor seed (NOT coerced to OFF); INFO log emitted matching the canonical message.
- **Test:** `test_hc_pre_conditioning_toggle_gates_all_branches`, `test_hc_pre_conditioning_off_preserves_active_flag_lifecycle`, `test_hc_pre_conditioning_independent_from_solar_banking`, `test_hc_pre_conditioning_restore_skips_unavailable`.
- **Sensor:** `sensor.ura_hvac_coordinator_house_state` shows `pre_conditioning_enabled: false` when switch is OFF; `pre_conditioning_zones: []` within one cycle.
- **Live:** Flip switch OFF on a forecast-hot day before 2 PM peak → next HC log line shows no "Pre-cool triggered" / "solar_banking" / "pre_arrival" execution within the following cycle; `pre_conditioning_zones` empty in the entity attrs. Flip back ON inside the pre-cool window → on the next cycle, conditions-met branches re-engage.

### D2a — OC Reasoning Sensor (`sensor.ura_optimizer_reasoning`)

A new SensorEntity on the existing URA: Optimization Coordinator device. **State** = a short plain-English headline for the most recent cycle (e.g. "Cycle ok — 3 findings (1 high), 2 shadow actions"). **Attributes** carry the structured per-cycle reasoning:
- `cycle_summary` (multiline string, ≤ 1024 chars): per-dimension one-liner verdicts ("would do / wouldn't / didn't because …").
- `cycle_actions_proposed`: list of `{dimension, severity, target, action, outcome, predicted_effect}` for the last cycle's findings with a `proposed_action`.
- `dry_run_veto_count`: integer — vetoes recorded against this cycle's intents (read from `OptimizationBroker._pending_vetoes` filtered by current cycle window).
- `last_cycle_at`: ISO of last evaluation (mirror of `_last_evaluation_iso`).

**Why a separate sensor (not just attrs on Status):** the reasoning text is large and dashboards want to surface it standalone; per parsimony, this is the ONE new entity in the cycle, and operator's explicit ask was a "Reasoning sensor".

**Files changed:** `sensor.py` (new class beside `OptimizerStatusSensor`), platform registration block at ~390.

**Recorder bloat check:** Attribute size bound is enforced by truncating `cycle_summary` to 1024 chars + capping `cycle_actions_proposed` at 20 entries (matches existing 20-cap on `OptimizerFindingsSensor.findings`). Cycle interval = 5 min → ≤ 288 writes/day. State changes only when `_last_evaluation_iso` changes (one per cycle) — bounded.

**Acceptance Criteria:**
- **Verify:** Entity registered on the Optimization Coordinator device; survives a reload.
- **Verify:** When the cycle emits zero non-META findings, `cycle_summary` reads "cycle_ok — no findings"; when ≥1 finding fires, every dimension that produced a finding is named.
- **Test:** `test_optimizer_reasoning_sensor_renders_findings`, `test_optimizer_reasoning_sensor_truncates_long_cycle_summary`, `test_optimizer_reasoning_sensor_dry_run_veto_count_from_broker`.
- **Live:** Within 6 minutes of HA restart on `develop`, `state_attr('sensor.ura_optimizer_reasoning', 'cycle_summary')` returns a non-null string ending with the most recent META `cycle_ok` line; `last_cycle_at` is within one cycle interval of now.

### D2b — Per-Dimension Verdict Attributes (on `OptimizerStatusSensor`)

Add `dimension_verdicts: dict[str, str]` to `OptimizerStatusSensor.extra_state_attributes`, with one entry per evaluator that ran in the last cycle (key = dimension token, value ∈ {`ok`, `advisory`, `degraded`, `critical`, `not_run`}). Verdict derived from the highest-severity finding produced by that evaluator this cycle:
- No findings → `ok`
- Highest severity `low` → `advisory`
- `medium` → `degraded`
- `high`/`critical` → `critical`
- Evaluator raised in the try/except → `not_run`

**Files changed:** `domain_coordinators/optimization.py` — populate `self._last_dimension_verdicts: dict[str, str]` at the end of `_run_cycle_body`; `sensor.py` — surface in `OptimizerStatusSensor.extra_state_attributes`.

**Why attr, not new sensor:** Operator parsimony; the StatusSensor is the existing "one glance" for OC health.

**Acceptance Criteria:**
- **Verify:** Every dimension in the evaluator tuple appears in `dimension_verdicts` after one cycle.
- **Verify:** A deliberately-raising evaluator (test-injected) yields `not_run` for its dimension only; other dimensions unaffected (A1 fix-up "one buggy dim can't blackhole" is preserved).
- **Test:** `test_optimizer_dimension_verdicts_populated_per_cycle`, `test_optimizer_dimension_verdicts_severity_mapping`, `test_optimizer_dimension_verdicts_not_run_on_evaluator_exception`.
- **Live:** `state_attr('sensor.ura_optimizer_status', 'dimension_verdicts')['comfort']` returns a verdict token (not None) on a healthy boot.

### D2c — LLM Reasoning Summary Attribute (on `OptimizerFindingsSensor`)

Add `llm_reasoning_summary: list[dict]` to `OptimizerFindingsSensor.extra_state_attributes`. Each entry: `{target_id, dimension, severity, description, reasoning}` for the most recent cycle's LLM-emitted findings (already populated as `_last_findings` LLM subset).
- `description` comes from the existing per-finding field.
- `reasoning` is a NEW optional field in the LLM response row; parser at `optimization_llm.py:914-948` extended to read `row.get("reasoning")` (string, optional, max 512 chars); malformed/missing → empty string (additive, no row rejection).

**Files changed:** `domain_coordinators/optimization_llm.py:914-948` (additive parse), `sensor.py:13822-13881` (attr emission), `domain_coordinators/optimization.py:189` (add optional `reasoning: str = ""` field to `OptimizationFinding`).

**Recorder bloat check:** `llm_reasoning_summary` is capped at the same 20-entry recent window already used for `findings`; per-row `reasoning` truncated to 512 chars. Sensor updates on `SIGNAL_OPTIMIZER_FINDING_EMITTED` (one per cycle since the v5.2.2 single-dispatch fix at `optimization.py:862`). Bounded.

**Acceptance Criteria:**
- **Verify (v5.2.1 shape confirmed in code):** Parser correctly handles `findings_json` string-of-JSON-array container (already confirmed at `optimization_llm.py:869-882`); adding the new `reasoning` field does NOT regress the existing strict-precedence parse.
- **Verify:** An LLM response with no `reasoning` field still emits findings (additive, not required).
- **Verify:** A malformed `reasoning` field (non-string, oversized) does NOT reject the row; `reasoning` is normalized to `""` or truncated.
- **Test:** `test_llm_parser_reads_optional_reasoning_field`, `test_llm_parser_reasoning_missing_keeps_finding`, `test_llm_parser_reasoning_oversized_truncated`, `test_findings_sensor_surfaces_llm_reasoning_summary`.
- **Live:** When OC's L2 LLM tier runs (premium cap permitting; may not fire same-day), `state_attr('sensor.ura_optimizer_findings', 'llm_reasoning_summary')` is a list (possibly empty until an LLM cycle fires); in-suite proves the wiring.

### D2d — Shadow Accuracy Percentage (`shadow_accuracy_pct` attr on `OptimizerStatusSensor`)

A rolling percentage of shadow predictions whose `predicted_effect` was confirmed by a later `observed_effect`. Feeds the eventual L1→L2 autonomy-promotion decision (per `PLANNING_OPTIMIZATION_COORDINATOR.md` Phase 5 framing — this is the missing OC-decision-side validator, not the Bayesian-side Pillar 4 reader).

**Validator loop (lightweight; runs INSIDE the existing 5-min cycle, no new timer):**
- Producer (already exists): shadow + dispatch paths in `_consider_apply` populate `predicted_effect` on each finding (`optimization.py:2397, 2803`).
- Consumer (NEW): once per cycle, walk the rolling `_last_findings` window for entries where `predicted_effect is not None` and `observed_effect is None` AND `(now - timestamp) ≥ OPTIMIZER_SHADOW_OBSERVE_DELAY` (NEW const, default 15 min). For each: read the relevant substrate (target entity / dimension-specific signal) and write `observed_effect = {match: bool, evidence: str, observed_at: iso}`. Match criterion is per-dimension (e.g. comfort: did room temperature move toward the target by ≥ predicted delta within window; sensor_health: did the flagged sensor recover).
- `shadow_accuracy_pct = round(100 * matches / total_with_observed, 1)` over a rolling window (NEW const `OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS`, default 7).
- Until `total_with_observed ≥ OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES` (NEW const, default 20), report `null` with sub-attr `shadow_accuracy_status = "warming_up"` (mirrors the Pillar-4 warm-up pattern at `optimization.py:96`).

**Constants (NEW):** `OPTIMIZER_SHADOW_OBSERVE_DELAY` (timedelta 15 min), `OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS = 7`, `OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES = 20`.

**Recorder bloat check:** Single numeric attribute on existing sensor; changes only when a shadow finding's observed_effect is newly written (bounded by per-cycle finding count, capped at `OPTIMIZER_MAX_FINDINGS_PER_CYCLE`). No new sensor entity.

**Scope guard — what this is NOT:**
- NOT the Bayesian Prediction-Accuracy dimension (v5.3.0 Pillar 4) — that scores Bayesian predictions vs reality; THIS scores OC's own shadow decisions vs reality. Reviewers must verify D2d does NOT collide with the existing `OPTIMIZER_DIMENSION_PREDICTION_ACCURACY` data path.
- NOT a real actuation path — shadow_accuracy_pct stays an observability number until operator dials L2; the autonomy gate is the existing `CONF_OPTIMIZER_AUTONOMY_LEVEL`.

**Acceptance Criteria:**
- **Verify:** Warm-up: with < `OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES`, `shadow_accuracy_pct` is `None` and `shadow_accuracy_status` is `"warming_up"`.
- **Verify:** Producer/consumer pairing — every finding that had `predicted_effect` set gets `observed_effect` set within `OPTIMIZER_SHADOW_OBSERVE_DELAY + 1 cycle`.
- **Verify (no collision with Pillar 4):** The Phase-4 `prediction_accuracy` dimension's evaluators and the new shadow validator do NOT both write the same `observed_effect` slot on the same finding; the shadow validator targets shadow-mode findings only (filter on `applied_outcome == OPTIMIZER_OUTCOME_SHADOW`).
- **Verify:** Validator failure is best-effort — one match-check raising does not blackhole the cycle (mirrors A1 evaluator pattern).
- **Test:** `test_shadow_accuracy_warmup`, `test_shadow_accuracy_pct_computed_over_window`, `test_shadow_validator_skips_non_shadow_outcomes`, `test_shadow_validator_observe_delay_respected`, `test_shadow_validator_does_not_clobber_pillar4_observed_effect`.
- **Live:** After ~2 hours on `develop`, `state_attr('sensor.ura_optimizer_status', 'shadow_accuracy_status')` ∈ {`warming_up`, `ready`}. If `ready`, `shadow_accuracy_pct` is a float in [0, 100].

---

## Recorder Bloat Audit (all D2 attrs combined)

| Attribute | Owner sensor | Update trigger | Size cap | Daily writes (worst-case) |
|---|---|---|---|---|
| `cycle_summary` | reasoning (NEW) | cycle tick (5 min) | 1024 chars | 288 |
| `cycle_actions_proposed` | reasoning (NEW) | cycle tick | 20 entries | 288 |
| `dry_run_veto_count` | reasoning (NEW) | cycle tick | int | 288 |
| `dimension_verdicts` | status | cycle tick | 12 keys | 288 (matches existing status churn) |
| `llm_reasoning_summary` | findings | LLM-cycle (≤ daily cap) | 20 × 512 chars | ≤ daily LLM cap (already enforced) |
| `shadow_accuracy_pct` | status | cycle tick | int/float | 288 |
| `shadow_accuracy_status` | status | cycle tick | enum | 288 |

Net: the StatusSensor already updates per cycle; new attrs ride existing churn. The new reasoning sensor adds one entity at the cycle cadence. No unbounded growth.

---

## Open Questions

1. **D1 release path on flip.** Solar banking's pain was that flipping the gate mid-bank required an explicit release (the v5.3.6 reviewer found two layers of "but we wrote a baseline" bugs). Pre-conditioning is different: the `_pre_cool_active` / `_pre_heat_active` flags self-clear at `PEAK_HOUR_START` / `OFF_PEAK_END_HOUR` (`hvac_predict.py:389,537`), and `_pre_conditioning_zones` is reset every cycle entry (`hvac_predict.py:372`). The PRESET dispatched by `_execute_zone_pre_cool` is NOT itself a setpoint write that needs reverting — it goes through DPM's `_last_emitted_range` apply. **Q: do we need a flip-OFF release like banking, or does the natural cycle boundary suffice?** Reviewer A's truth-table must answer this explicitly with a test for "flip OFF mid pre-cool window, before peak start." Planner's reading: NO explicit release needed because preset re-issue at the next DPM tick will overwrite the pre-cool offset; but the planner is hedging — confirm in build.

2. **D2d match criterion per dimension.** The match function for "did the predicted effect happen" is dimension-specific. For comfort the heuristic is straightforward (temp moved toward target). For sensor_health, "predicted: sensor will recover" is hard to score crisply. **Q: ship D2d initially over comfort + occupancy_accuracy only, mark other dimensions as `unscorable` in `observed_effect.match`, and expand in a follow-up?** Recommended: yes, narrow at first to keep the rolling % meaningful; document the scorable subset in the planning doc once confirmed.

3. **D2c `reasoning` LLM prompt update.** Surfacing per-row LLM reasoning is only useful if the LLM is asked to emit it. The structured-output schema (referenced at `config_flow.py:1627-1634` per parser comment) defines `findings_json` shape. **Q: extend the structured-output JSON Schema in this cycle (additive: `reasoning` optional)?** If yes, ships in same PR; if no, the attr stays empty until a follow-up cycle updates the schema. Planner recommendation: include the schema bump in this cycle (single LoC delta, additive, no regression risk per existing strict-precedence parse).

---

## Summary (for the operator response below)

See the assistant message accompanying this file.
