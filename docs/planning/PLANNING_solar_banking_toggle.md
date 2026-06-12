# Planning — Solar HVAC Banking Master Toggle

> **RECONSTRUCTED 2026-06-11.** The original planner-authored doc was lost
> untracked during a merge cleanup (main-session error: removed before
> verifying the feature branch carried it). Rebuilt from the planner's
> summary, the build report, and the Tier 1 review ledger
> (`docs/reviews/code-review/solar_banking_toggle.md`) — which together
> preserve every load-bearing decision. Tier classification and outcomes
> are as executed.

**Status:** BUILT + REVIEWED (4ff0377 → 682b269) · **Tier:** 1 (single adversarial review)
**Operator trigger (2026-06-11):** "It fires all the time on good solar day, pins HVAC and drives up the energy use. It should be able to be turned off easily from the EC device UI itself."

## Institutional context (as verified by the planner + validated in build/review)
- Banking lives in `domain_coordinators/hvac_predict.py` (`_solar_banking_zones`, `_solar_bank_triggered_today`, `solar_bank_floor`/`solar_bank_soc_min` tunables plumbed from hvac.py; `solar_banking_zones` attr at hvac.py house-state sensor). No enable/disable gate existed.
- REUSED: `_ec_switch_factory` (switch.py:758) mirroring `OccupancyWeightedPredictionSwitch` (RestoreEntity replay + ready-signal + retry). `CONF_HVAC_SOLAR_BANK_FLOOR` precedent = v4.7.25 tunable family.
- NEW: `CONF_HVAC_SOLAR_BANK_ENABLED` (hvac_const.py, default True), `ECSolarBankingSwitch`, EC `solar_banking_enabled` property, config-flow BooleanSelector.

## Deliverables (as executed)
1. **D1-D4** EC-device switch (default ON) gating `_check_pre_conditioning`'s banking branch; `banking_enabled` attr distinguishes operator-OFF from conditions-unmet.
2. **Release path** (plan's "free release via preset re-issue" was FALSIFIED in build — the `_last_emitted_range` throttle blocks re-emits; review then falsified the build's version too — live `zone.target_temp_*` post-banking IS the banked value): final implementation sources baseline from `HVACCoordinator._last_emitted_range` (preset-resolved fallback), syncs the throttle map post-release, one-shot restart reconciliation (gate OFF + live setpoint >0.5°F below baseline), tracked-zone lifecycle survives the banking window closing.
3. **Placement:** EC device per operator-explicit request (trigger inputs are EC solar/SOC even though logic runs in the HVAC predictor).

## Acceptance (validated in-suite; Live criteria for Review D)
- **Test:** 18 cycle tests incl. release-uses-emitted-range, restart reconciliation, flip-after-window — all driving the real `_check_pre_conditioning`/release path.
- **Live:** good-solar-day with toggle OFF → `solar_banking_zones` stays empty, `banking_enabled: false`; flip OFF mid-bank → zones release within one cycle to the emitted baseline; restart with gate OFF after banking → one-shot reconciliation INFO.

## Known/backlog
- Banking ratchets toward the floor across cycles (reads live already-banked setpoints) — pre-existing, in-code comment, backlog.
- RestoreEntity wins over the config-flow seed post-install (sibling-EC semantics; helper text states this honestly).
