# URA v5.4.0 — HC Pre-Conditioning Master Toggle + Optimizer Observability

Operator-pruned menu (2026-06-11). Two parts: a master toggle for predictive HVAC pre-conditioning, and an observability suite on the Optimization Coordinator so its shadow-mode reasoning is readable from the dashboard (feeding the eventual L1→L2 autonomy decision).

Tier 2: build + 2 fix-ups + validator + 2 framing-disjoint reviews + focused confirm. Ledger: `docs/reviews/code-review/hc_precool_oc_observability.md`. Plan: `docs/planning/PLANNING_hc_precool_toggle_oc_observability.md`.

## What ships

### D1 — HC pre-conditioning master toggle
`switch.ura_hvac_coordinator_pre_conditioning` on the HVAC Coordinator device, default ON (sibling of the v5.3.6 Solar HVAC Banking toggle). Guards the top of `_check_pre_conditioning` (predictive pre-cool on forecast-hot days / pre-heat on forecast-cold) — options write-back is sole source of truth, read live per cycle, Bug Class #52 restore guard.
- **Flip-OFF release:** toggling OFF mid-pre-condition releases the in-flight pre-cool/pre-heat to the **true** baseline within one cycle (sourced from `_last_emitted_range`, NOT the offset-echoing live setpoint — the v5.3.6 banking-release-bug class, verified avoided). Same-day flip-back-ON re-arms (the `_triggered_today` flags are cleared on release).
- **Scope:** gates *predictive* pre-conditioning only. EC's reactive TOU pre_cool/pre_heat/coast/shed (a separate setpoint path) is intentionally NOT suppressed — noted in the switch helper text.
- `pre_conditioning_enabled` attr on the HVAC house-state sensor.

### D2 — Optimizer observability (parsimony: one new entity, rest are attrs)
- **D2a — `sensor.ura_optimizer_reasoning`** (the one new entity): `cycle_summary` (plain-English what-it-would-have-done), `cycle_actions_proposed`, `dry_run_veto_count` (from the broker's pending vetoes). Size-capped, per-cycle cadence.
- **D2b — `dimension_verdicts`** attr on `OptimizerStatusSensor` (per-dimension severity, `not_run` when an evaluator raises).
- **D2c — `llm_reasoning_summary`** attr on `OptimizerFindingsSensor` + a malformed-tolerant parser-side `reasoning` field (the structured-output schema bump is deferred to the next LLM-tier cycle; parser is forward-compatible).
- **D2d — `shadow_accuracy_pct` / `shadow_accuracy_status`** on `OptimizerStatusSensor`, scoring COMFORT + OCCUPANCY_ACCURACY only (others `unscorable`). Reads the **real** room substrate (`_iter_room_entries` / `_state_value` against curated `CONF_TEMPERATURE_SENSOR` / `CONF_OCCUPANCY_SENSORS`) — a review caught and fixed an initial build that read a phantom `room_coordinators` surface (would have pinned the gauge inert). Scoring is **resolved-vs-persisted** against each finding's OWN band (`payload["bounds"]`, default `[68,76]`) — a second review caught and fixed a degenerate hardcoded-band version that would have trended accuracy falsely to 100%. Statuses: `warming_up` (pre-sample), `no_observable_data` (wired but oracle finds nothing), `ready`.

## Live Validation — Validated 2026-06-13 (restart 13:47 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| Clean restart, zero URA ERRORs, 40/40 entries | PASS | 40/40 loaded; no URA ERROR lines (only non-URA esphome sensor noise) |
| HC pre-conditioning toggle present + ON | PASS | `switch.ura_hvac_coordinator_hvac_pre_conditioning` = `on` (default) on the HVAC Coordinator device |
| OC Reasoning sensor (D2a) | PASS | `sensor.ura_optimization_coordinator_optimizer_reasoning` after first cycle: `cycle_summary` = "cycle ok — 1 finding(s), 1 low / prediction_accuracy: 1 finding(s), highest=low"; `cycle_actions_proposed: []`; `dry_run_veto_count: 0` |
| dimension_verdicts (D2b) | PASS | Populated after first cycle: 11 dimensions `ok`, `prediction_accuracy: advisory` (real severity-mapped verdict reflecting the low finding) |
| shadow_accuracy (D2d) — honest, not degenerate | PASS | `shadow_accuracy_status: warming_up`, `shadow_accuracy_pct: null` — both at boot AND after a real cycle. NOT pinned-inert (the phantom-oracle bug, fixed) and NOT falsely-100% (the hardcoded-band bug, fixed). The two-review payoff confirmed live. |
| `llm_reasoning_summary` (D2c) | DEFERRED-OBSERVABLE | Attr present; populates only once an LLM-tier (Tier-2) cycle emits `reasoning` — none ran in this window (shadow mode, low findings). Parser forward-compat confirmed in-suite. |
| Recorder cadence | PASS (by design) | All new attrs ride the single per-cycle OC dispatch; verified in-suite, no per-tick churn |
| **Operator hands-on: flip OFF mid-pre-cool → release; flip ON same-day → re-engage** | DEFERRED | Requires a forecast pre-cool day with an active pre-condition window; mutation-anchored in-suite (release-to-true-baseline + same-day re-arm tests) |

Note: OC status reads `degraded` (house_score 55, 6 window findings) — pre-existing dead-sensor backlog under the v5.3.4 recalibrated vocabulary (Garage B Protect + Jaya devices), NOT a v5.4.0 regression.

*D2d shadow accuracy remains preliminary until samples accrue across cycles (it stays `warming_up` until MIN_SAMPLES of resolved/persisted findings) — re-check that it reaches `ready` (not stuck, not 100%) over the coming days.*
