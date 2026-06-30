# URA v5.7.1 — Energy Saver Pre-Cool unification (Tier 3)

Unifies the two overlapping over-cool mechanisms (forecast-driven "weather pre-cool" + PV-driven "solar banking") into ONE **PV-aware** feature. It pre-cools the house thermal mass with cheap/free solar energy ahead of peak — but only when there's **real solar export surplus** — so it no longer cools on a hot-forecast day with no sun. Decision lives in the HVAC predictor; the operator controls it from the **EC device**.

## What ships (Tier 3 — 4 framing-disjoint reviews + checkpoint)
- **Unified PV-aware trigger** (`_should_energy_precool`): fires only when toggle ON ∧ live grid export > 500 W ∧ off-peak window ∧ summer/shoulder ∧ SOC floor ∧ `mode==normal`. The PV (and mode) check runs **every cycle including re-engagement**, so a passing cloud stops it (the old weather-pre-cool persistence + banking PV-gate are reconciled).
- **EC-device surfaces:** switch **"Energy Saver Pre-Cool"**, Number **Offset** (default 2 °F), Select **Scope** (`occupied_only` / `whole_house` / `auto_pv_tiered`, default `auto_pv_tiered` — occupied-only normally, whole-house only under real export surplus, re-checked at dispatch). Separate from the master "28 · HVAC Predictive Conditioning" (pre-arrival/pre-heat unaffected).
- **Retires solar banking:** old toggle migrated → energy-precool, **honoring an operator's runtime banking-OFF** (read from the switch's RestoreEntity, not just the options seed) so a disabled feature is never silently re-enabled; setup-order-safe (migrates before the EC reads options); old switch entity orphan-cleaned (Bug Class #46).
- 72 °F floor enforced at a single chokepoint (`_execute_zone_pre_cool`).

## Falsifiable invariant (I1)
Energy Saver Pre-Cool actuates a cooler setpoint in NO reachable path (incl. cross-cycle re-engagement) without (toggle ON ∧ live export surplus ∧ normal mode); never below 72 °F.

## Review trail
4 framing-disjoint → all FIX-FIRST (2 CRIT migration: options-vs-RestoreEntity + setup-order race; 1 HIGH re-engagement-re-cools-without-PV; missed-rename; SOC-None floor; flaky test; 3 deleted-coverage regressions). 3 fix-up rounds; **B re-pass caught a 2nd CRIT** — the migration "fix" awaited a *synchronous* HA API (`async_get`) and its async-mock test masked it → inert in production → fixed (sync call + test mock now matches the real `@callback` contract). **D re-pass SHIP** (I1 holds, no N+1, floor single-chokepoint). Every money-critical site mutation-anchored + orchestrator-verified (D-HIGH-1 cross-cycle PV; B-1 RestoreEntity-OFF; B-RE-1 await-on-sync). Suite at the 35-failed baseline, +15 cycle tests.

## Deferred (fast-follow)
Strings/translations for the new entity labels — they render via `_attr_name` (cosmetic only); translations cleanup if dashboards need the keys.

---

## Acceptance

```yaml
version: 5.7.1
hypotheses:
  - id: H1
    name: ura_v571_deployed
    description: URA v5.7.1 is the running HACS-installed version.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.7.1" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: no_energy_precool_error_storm
    description: No recurring URA error after the pre-cool unification + banking migration.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
  - id: H3
    name: energy_precool_scope_surface_live
    description: The Energy Saver Pre-Cool scope diagnostic is published on the HVAC house-state sensor.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.ura_hvac_coordinator_hvac_house_state, attribute: energy_precool_scope }
    expected: { condition: "!=", value: "unknown" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 24h }
```

> Shipwatch note: pre-cool only actuates on real solar export, so live "fired correctly" needs a good-solar window; the migration + entity presence are immediately checkable. The HA adapter stub is backlogged → hypotheses resolve `pending` until it ships. Verify entity/attribute names live before trusting `confirmed`.

## Live Validation — *(prospective; written back post-restart)*
- **L1** — installed_version `v5.7.1`; zero URA boot ERRORs.
- **L2** — the 3 EC-device entities present (`switch`/`number`/`select` for Energy Saver Pre-Cool); old `switch.ura_energy_solar_banking` orphan gone.
- **L3 (migration)** — `energy_precool_enabled` reflects the operator's prior banking choice (OFF stays OFF); `energy_precool_offset`/`_scope` attrs on the HVAC house-state sensor.
- **L4 (I1)** — pre-cool fires only on a real-export window (standing watch); never on a hot-but-no-sun day. In-suite-authoritative; live note over the next good-solar day.
