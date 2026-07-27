# PLANNING: HVAC AC-Ramp kWh-Avoided → Savings Estimate (the deferred #7 D6)

**Author:** orchestrator (session 2026-07-26)
**Status:** Plan only — filed, not built. Operator go to build TBD.
**Proposed tier:** **Tier 2** (two framing-disjoint reviews). Additive + display-only
(no decision consumer), restart-persistence already correct — but it (a) extends the
persisted `ac_ramp_events.notes` payload shape and (b) introduces a new $-valued surface,
so it earns two reviews, not one.
**Origin:** This is D6 from `PLANNING_energy_savings_unification.md`, deliberately deferred
from the v5.32.0 (#7) cycle. Operator 2026-07-26: *"not billing-grade, but it should
roughly estimate the savings from HVAC ops."*

---

## Guiding constraint (operator-ratified 2026-07-26)
**NOT billing-grade — a rough estimate of HVAC-ops savings is the goal.** Do NOT chase
precision (the fixed-projection assumption stays). Inherit the existing `rough_estimate /
not billing-grade` disclaimer onto every new sensor. The value is a *trend + ballpark $*,
explicitly caveated.

---

## Institutional context verified

### Files read end-to-end (this inspection, 2026-07-26)
- `custom_components/universal_room_automation/domain_coordinators/hvac_override.py`:
  - `:212-285` `_impact_cache` + `_refresh_impact_cache` (today via `since=start_of_local_day()`, total via `days=None`).
  - `:1869-1924` nudge classification + **per-event kwh_avoided compute** (`kwh_avoided = (kwh_rate_before − post_min) × AC_KWH_AVOIDED_PROJECTION_CAP_MIN/60`, only when `effective` and `delta>0`), persisted into the event `notes` string (`kwh_avoided=…;post_min=…;sample_count=…;classification=…`).
- `custom_components/universal_room_automation/database.py`:
  - `:7047-7107` `log_ac_ramp_event` (writes the `notes` string).
  - `:7138-7208+` `get_ac_ramp_kwh_avoided(days=None, since=None)` — aggregates `nudge_evaluated` rows, parses per-event kwh_avoided from `notes`, `since` wins over `days`; excludes `effective IS NULL` and `triggered_by='manual'`.
  - `:1330-1373` `ac_ramp_events` DDL + `effective` column migration.
- `custom_components/universal_room_automation/sensor.py`:
  - `:10784-10833` `HVACACKwhAvoidedTodaySensor` (TOTAL_INCREASING, kWh, restart-safe via DB re-derive).
  - `:10836-10870+` `HVACACKwhAvoidedTotalSensor` (RestoreEntity + DB all-time sum).
  - `:298-299` registration (today + total ONLY — **no billing_cycle**).

### Consumers (grep) — display-only, confirmed
- `sensor.py` (the two D8 sensors), `button.py:1142` (a button attribute). The aggregate `false_positive_rate` in the cache is display; per-event `escalate` (not the aggregate) drives escalation. **No coordinator reads kwh_avoided for a decision.** Safe to extend additively.

### Prior art (REUSE, not NEW)
- **Rate lookup:** `_get_effective_rate_kwh(hass)` (energy_billing.py:28) — canonical TOU-effective import rate. **REUSE** for the $ conversion. Do NOT add a new rate helper.
- **Bill-cycle boundary:** `CONF_ENERGY_BILL_CYCLE_DAY` (energy_const.py:260, DEFAULT 23) + the EC cycle-reset logic. **REUSE** for the `_billing_cycle` scope (mirror the pattern #7 used).
- **Projection cap:** `AC_KWH_AVOIDED_PROJECTION_CAP_MIN` — already a module constant (correct rung: change requires review). No new knob.
- **Notes payload + parser:** `notes` is a `;`-separated `key=value` string parsed at database.py (`split(';')` then `split('=')`). Any new key is back-compatible with the tolerant parser.

### Related planning docs
- `PLANNING_energy_savings_unification.md` (this is its D6; §3.3 already reasoned the $ family should stay standalone, not folded into `total_savings`).
- `PLANNING_v4.5.12_ac_ramp_observability.md` — provenance of the kWh family + the "trend-watching only" disclaimer.

---

## Foundation verification (accuracy — "accurate for what it is?")

**Verdict: accurate for a trend/ballpark; two known levers, both acceptable under the operator's "rough estimate" constraint.**

1. **Fixed 30-min projection** (`× AC_KWH_AVOIDED_PROJECTION_CAP_MIN/60`) — assumes the avoided load would have run exactly the capped window. Coarse but conservative. **Keep** (operator: not billing-grade).
2. **`delta` uses `post_min`** (trailing-window minimum) → mild **optimism bias**. Bounded by the `effective` gate + <0.3 kW signal floor. **Optional** honesty tweak below.
3. **Restart-persistence is already correct** — total re-derives from the DB (`days=None` sum) with a RestoreEntity bridge; today re-derives since local-midnight. Unlike the #7 peak-avoidance bug, there is **nothing to fix** here.

---

## The double-count trap (design decision, ratified)
A $ value on AC-ramp avoidance must **NOT** be folded into the #7 `total_savings` family. A
reduced AC load means less grid import *and/or* less battery discharge — crediting AC-ramp $
AND peak-avoidance/arbitrage on the same avoided kWh would double-count. **AC-ramp savings
stays its own standalone family.** (Consistent with #7 plan §3.3.)

---

## Deliverables

### D1: `_billing_cycle` scope for kWh-avoided
Add `HVACACKwhAvoidedBillingCycleSensor` (kWh, TOTAL) summing `nudge_evaluated` events since
the current bill-cycle start. Extend `_refresh_impact_cache` to compute a `kwh_avoided_cycle`
via `get_ac_ramp_kwh_avoided(since=<cycle_start>)` (reuse the EC cycle-start helper).

**Acceptance:**
- **Verify:** `kwh_avoided_cycle ≥ kwh_avoided_today` (cycle ⊇ today) and resets on `bill_cycle_day`.
- **Sensor:** `sensor.ura_hvac_ac_kwh_avoided_billing_cycle` (kWh/ENERGY/TOTAL), registered on the HVAC device.
- **Test:** `test_ac_kwh_avoided_billing_cycle_reset`, `test_cycle_superset_of_today`.
- **Live:** populated within a refresh cycle post-restart.

### D2: Standalone $ savings family (the headline)
New `ac_ramp_savings_{today,billing_cycle,lifetime}` (USD, MONETARY, TOTAL). Value each event's
persisted `kwh_avoided` at the **TOU rate captured at nudge-eval time**. To do this accurately,
capture `rate=<effective_rate>` into the event `notes` at log time (`hvac_override.py:1909`, one
new `key=value`), and have `get_ac_ramp_kwh_avoided` (or a sibling `get_ac_ramp_savings`) parse
it. **Forward-only:** pre-existing events lacking a captured rate contribute kWh but $0 (or fall
back to the current effective rate with a documented caveat — reviewer's call). Inherit the
`rough_estimate` disclaimer.

**Acceptance:**
- **Verify:** for an effective nudge logged post-deploy, `ac_ramp_savings_today ≈ kwh_avoided_today × captured_rate` (within rounding).
- **Verify:** no double-count — this family is NOT summed into `energy_savings_total_*`.
- **Sensor:** 3 sensors USD/MONETARY/TOTAL, no recorder rejection; `methodology` attr states the rough-estimate + rate-at-nudge-time basis.
- **Test:** `test_ac_ramp_savings_values_at_captured_rate`, `test_ac_ramp_savings_excluded_from_total`, `test_savings_rough_estimate_caveat_present`.
- **Live:** after an effective nudge fires, `ac_ramp_savings_today` > 0.

### D3 (optional honesty tweak): `post_min` → mean post-rate
Replace the trailing-window minimum with the trailing-window **mean** in the `delta` compute
(`hvac_override.py:1896`) to drop the optimism bias. Small, self-contained; changes the recorded
per-event value going forward (not retroactive). Include ONLY if it doesn't complicate review;
otherwise defer.

**Acceptance:**
- **Verify:** for a synthetic post-window, computed delta uses mean not min.
- **Test:** `test_kwh_avoided_delta_uses_mean_post_rate`.

### D4: Dashboard surface
ura-v8 Climate tab (or the Energy Savings section): show AC-ramp $ saved (today / cycle /
lifetime) + kWh-avoided, status-only, with the "rough estimate" caveat visible. Mirror the D7
Energy Savings markdown-grid style.

**Acceptance:**
- **Verify:** tile renders the 3 epochs × ($ + kWh), values match sensor states, caveat shown.
- **Live:** renders after D2 sensors populate.

---

## Naming / knobs
- New kWh sensor: `sensor.ura_hvac_ac_kwh_avoided_billing_cycle` (matches existing `_today`/`_total`; the `_total`→`_lifetime` rename is parked cosmetic, same as #7).
- $ family: `sensor.ura_hvac_ac_ramp_savings_{today,billing_cycle,lifetime}`.
- No new operator knobs. Rate = REUSED `_get_effective_rate_kwh`. Projection cap = existing module const.

## Tier & review framings (Tier 2)
- **A — Accuracy + rate-capture + notes back-compat:** the $ math values kWh at the right rate; the new `notes` key is parser-back-compatible (old rows tolerated); optimism-bias tweak (if D3) is correct; rough-estimate caveat present on all new surfaces.
- **B — Additive wiring + scope + persistence + registration:** billing-cycle reset mirrors EC; no regression to the existing today/total sensors; new sensors register cleanly (no recorder rejection); restart-safe (DB re-derive); $ family provably excluded from `energy_savings_total_*` (no double-count).

## Non-goals
- NOT billing-grade; do not replace the fixed-projection model.
- Do NOT fold AC-ramp $ into the #7 `total_savings` family (double-count).
- No decision-logic changes; kwh_avoided/savings remain display-only.
</content>

---

## SHIPPED — v5.33.0 (2026-07-27)
Built + Tier-2 reviewed (2 framing-disjoint; 1 HIGH brittle-slice-test + mediums/lows fixed; no-double-count independently verified) + deployed + live-validated. D1 (billing_cycle kWh), D2 (standalone $ family, forward-only, rate-at-nudge-eval), D4 (ura-v8 Climate "AC Ramp Savings" card) all shipped. D3 (post_min→mean) deferred per escape clause. Live: 6/7 hypotheses PASS (H4 $-accrual forward-only, organic). See `docs/readmes/README_v5.33.0.md` + `docs/reviews/code-review/v5.33.0_hvac_ac_ramp_savings.md`.
