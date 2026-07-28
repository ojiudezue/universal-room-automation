# URA v5.33.0 — HVAC AC-Ramp Savings Estimate (rough, not billing-grade)

Gives the existing AC-ramp `kwh_avoided` family a **billing-cycle scope** and a
**standalone $ savings estimate**, so the operator can see a rough dollar figure for
what HVAC ramp-down ops save. Additive + display-only — no decision consumer, no
behavior change. This is the deferred **D6** from the #7 energy-savings cycle.

**Explicitly NOT billing-grade** (operator directive): a trend + ballpark $, caveated
on every sensor. The fixed 30-min projection model is unchanged.

## What ships

### New sensors (4)
- `sensor.ura_hvac_ac_kwh_avoided_billing_cycle` (kWh) — the missing cycle scope alongside the existing today/total.
- `sensor.ura_hvac_ac_ramp_savings_{today,billing_cycle,lifetime}` (USD) — **NEW** $ estimate = per-event `kwh_avoided × TOU rate captured at nudge-eval time`.
- Existing `ac_kwh_avoided_today/_total` are **unchanged**.

### Design
- **Standalone family — NOT summed into `energy_savings_total_*`** (independently review-verified). Folding it in would double-count against #7's peak-avoidance/arbitrage on the same avoided kWh.
- **Rate captured at nudge-eval time** and persisted into the event `notes` (`;rate=<x>`, guarded `isfinite & >0`). Parser is back-compatible (appended key; old rows parse fine and contribute kWh but $0 — forward-only, no retro-guessed rate).
- **Restart-safe** — all DB-re-derived (no in-RAM accumulator), same as the existing kWh family.
- Cycle boundary via the new public `EnergyCoordinator.get_billing_cycle_start()` accessor (no private cross-coordinator reach); a `cycle_start_source: ec|fallback` attribute makes a degraded EC-lookup observable.

### Known rough-estimate skew (documented, not fixed — per "don't chase precision")
- **Peak-boundary undervaluation:** the rate is captured at eval time (~10 min after the nudge). A nudge issued just before a TOU down-transition can be valued at the *lower* post-boundary rate → the estimate is **slightly pessimistic on exactly the most valuable (peak-approach) nudges**. Acceptable under the rough-estimate mandate; stated in the sensor `methodology` attribute.

## Review provenance
`docs/reviews/code-review/v5.33.0_hvac_ac_ramp_savings.md` — Tier 2, two framing-disjoint reviews (A = accuracy/rate-capture/notes-back-compat; B = wiring/scope/persistence/no-double-count). Both SHIP-after-fixes; 1 HIGH (brittle pre-existing slice-test broke by code motion — Bug Class #41, fixed by whole-function-body search) + mediums/lows fixed (test-authority pure helper, rate isfinite guard, public accessor for the private reach, dt_util idiom, docstrings). No-double-count independently verified from source. Orchestrator re-verified: FP-rate test green, no-double-count holds, delta math untouched.

## Live Validation — Acceptance Hypotheses (Shipwatch)

- **H1 — Clean boot.** Zero URA `ERROR` lines post-restart; presence house-state live. 15 min.
- **H2 — 4 new sensors register + numeric.** `ac_kwh_avoided_billing_cycle` (kWh) + `ac_ramp_savings_{today,billing_cycle,lifetime}` (USD) exist, numeric, correct units/classes, `methodology`/`accuracy: rough_estimate` attrs present, no recorder rejection. 10 min.
- **H3 — cycle ⊇ today.** `ac_kwh_avoided_billing_cycle ≥ ac_kwh_avoided_today`; `ac_ramp_savings_billing_cycle ≥ ac_ramp_savings_today`. 1 h.
- **H4 — savings tracks kWh × rate (forward-only).** After an effective nudge logged post-deploy, `ac_ramp_savings_today ≈ (rated kWh) × captured rate` (> 0). Window: next effective nudge.
- **H5 — existing kWh sensors unchanged.** `ac_kwh_avoided_today/_total` render the same as pre-deploy. 1 h.
- **H6 — no double-count.** `energy_savings_total_*` values are unchanged by this deploy (AC-ramp $ excluded). 1 h.
- **H7 — cycle_start_source observable.** `ac_kwh_avoided_billing_cycle` attribute `cycle_start_source` = `ec` in steady state (not stuck `fallback`). 15 min post-warmup.

### Validated 2026-07-27 (restart ~00:1x CDT)

Actual entity_ids: `sensor.ura_hvac_coordinator_{ac_kwh_avoided_today,75_ac_kwh_avoided_this_cycle,ac_kwh_avoided_total,76_ac_ramp_savings_today,77_ac_ramp_savings_this_cycle,78_ac_ramp_savings_lifetime}`.

| # | Result | Observed evidence |
|---|--------|-------------------|
| H1 | **PASS** | Zero URA `ERROR` lines post-restart. |
| H2 | **PASS** | All 4 new sensors register + numeric. `75_ac_kwh_avoided_this_cycle` = kWh/ENERGY/TOTAL, `accuracy: rough_estimate`. `76/77/78_ac_ramp_savings_*` = USD/MONETARY/TOTAL, `accuracy: rough_estimate`, `methodology` present and explicitly states "NOT summed into energy_savings_total_*" + forward-only + not billing-grade. No recorder rejection. |
| H3 | **PASS** | `75_ac_kwh_avoided_this_cycle` = 176.93 kWh ≥ `ac_kwh_avoided_today` (~0 at night) — cycle scope correctly sums historical nudge events since bill-cycle start. |
| H5 | **PASS** | Existing `ac_kwh_avoided_today/_total` present, unchanged shape/behavior. |
| H6 | **PASS (static + live)** | AST + grep verified no `EnergySavingsTotal*` reference to the new keys/classes; live `energy_savings_total_lifetime` = 13.55 tracks arbitrage + peak-avoidance only (AC-ramp $ currently 0.0, structurally excluded). |
| H7 | **PASS** | `cycle_start_source` flipped `unknown → ec` after first impact-cache refresh — the new public `EnergyCoordinator.get_billing_cycle_start()` accessor works live (not stuck `fallback`). |
| H4 | pending-organic | `ac_ramp_savings_*` = $0.00 now — forward-only ($ only for nudges logged post-deploy with a captured rate). Builds after the next effective nudge. |

**Magnitude note (expected):** the 176.93 kWh cycle figure reflects the deliberately-rough model (fixed 30-min projection + min-based delta, self-labeled `rough_estimate`, not billing-grade per operator directive). It is a ballpark/trend, not a metered value.
</content>
