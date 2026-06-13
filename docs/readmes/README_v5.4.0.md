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

## Live Validation (Review D) — prospective criteria
- [ ] Clean restart; zero URA ERRORs; 40/40 entries.
- [ ] `switch.ura_hvac_coordinator_pre_conditioning` visible on HVAC Coordinator device, ON; `pre_conditioning_enabled: true` attr.
- [ ] `sensor.ura_optimizer_reasoning` present with a plain-English `cycle_summary` after an OC cycle; `dry_run_veto_count` numeric.
- [ ] `OptimizerStatusSensor` shows `dimension_verdicts` + `shadow_accuracy_status` (expect `warming_up` initially; should reach `ready` for comfort/occupancy after samples accrue — NOT pinned, NOT falsely 100%).
- [ ] `OptimizerFindingsSensor` `llm_reasoning_summary` attr present (populated once an LLM-tier cycle emits `reasoning`).
- [ ] **Operator hands-on (forecast pre-cool day):** flip the toggle OFF mid-pre-cool → setpoints release to baseline within one cycle; flip ON same day → pre-cool re-engages.
- [ ] No recorder-bloat: new attrs change at most once per OC cycle.

*Replaced with observed results post-restart per the README write-back rule. Note: D2d shadow accuracy is a freshly-corrected metric (two review fixes) — interpret its first readings as preliminary until a few cycles accrue.*
