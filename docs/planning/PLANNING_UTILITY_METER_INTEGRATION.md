# Cycle B: Utility Meter + Emporia Mains Integration

**Risk: MEDIUM** — Multiple data sources, billing calibration logic, DB schema implications. No destructive changes but complexity in reconciliation math.

## Context

Three independent energy measurement sources exist:
1. **Enphase Envoy** — solar gateway, lifetime counters, net consumption CT
2. **Emporia Vue** — mains panel CTs, already configured as `CONF_ENERGY_GRID_IMPORT_ENTITY` / `CONF_ENERGY_GRID_EXPORT_ENTITY`, used by CostTracker for billing but NOT stored in energy_history
3. **SmartHub (utility company)** — `sensor.smarthub_energy_monthly_usage_*`, net metered monthly kWh (what the utility actually bills), updates daily at midnight

Currently URA's Energy Coordinator uses Envoy as primary, Emporia as CostTracker input, and SmartHub not at all. The `grid_import_2` column in `energy_history` exists but is never populated.

## Current Column Usage

| Column | Source | Content |
|--------|--------|---------|
| `grid_import` | Envoy `net_power` (positive half) | Instantaneous grid import power (kW) |
| `grid_import_2` | None | Empty — never populated |
| `solar_export` | Envoy `net_power` (negative half) | Instantaneous solar export power (kW) |

No separate `grid_export` column exists — export is captured via `solar_export`.

## Deliverables

### B1: Config Flow — Utility Meter Entity Picker

Add optional entity picker for the utility company meter.

**Config key:** `CONF_ENERGY_UTILITY_METER_ENTITY`
**Selector:** `domain="sensor", device_class="energy"` (kWh, total_increasing)

### Acceptance Criteria
- **Verify:** Entity picker appears in energy config flow
- **Verify:** Saving with no entity selected works (optional)
- **Verify:** Selected entity persisted and readable by EC on startup

### B2: Populate `grid_import_2` with Emporia Mains Power

Store the Emporia mains import power in `grid_import_2` alongside Envoy's `grid_import`. This gives us two independent power readings at each 15-min snapshot for historical comparison.

**Source:** `CONF_ENERGY_GRID_IMPORT_ENTITY` (already configured) — read the state, convert to kW, store in `grid_import_2`.

Note: This is instantaneous power (kW), same as `grid_import`. The Emporia monthly energy sensors (kWh) are cumulative — we don't store those in energy_history (which logs power snapshots, not energy totals).

### Acceptance Criteria
- **Verify:** `grid_import_2` populated in energy_history rows when Emporia entity is configured
- **Verify:** `grid_import_2` remains NULL when Emporia entity is not configured (backwards compatible)
- **Live:** Query `SELECT grid_import, grid_import_2 FROM energy_history ORDER BY timestamp DESC LIMIT 5` — both columns populated

### B3: Bill Prediction Calibration

Compare URA's cycle import total (Envoy-derived) against utility meter reading. Surface divergence. When divergence is sustained, switch prediction source.

**Logic:**
1. Read utility meter value each decision cycle
2. Compare against `CostTracker._import_kwh_cycle` (Envoy-derived cumulative import for this billing cycle)
3. Compute divergence: `abs(utility - envoy) / max(utility, envoy, 1.0) * 100`
4. Store rolling 3-day divergence average
5. If rolling divergence > 10% for 3+ days:
   - Switch `predicted_bill` to use utility meter extrapolation
   - Log activity event
6. If rolling divergence drops below 5%:
   - Switch back to Envoy-derived (self-healing)
7. Surface in sensor attributes: `prediction_source: "envoy" | "utility_meter"`, `utility_divergence_pct: 12.3`

**Complication:** The utility sensor is `total_increasing` with monthly reset. URA's billing cycle day may differ from the utility's billing cycle start. Need to align: track utility delta since URA's `_cycle_start_date`, not since the utility's `last_reset`.

### Acceptance Criteria
- **Verify:** Divergence % visible in predicted_bill sensor attributes
- **Verify:** Prediction source switches to utility meter after 3 days of >10% divergence
- **Verify:** Self-heals back to Envoy when divergence drops
- **Sensor:** `prediction_source` attribute on `sensor.ura_energy_predicted_bill`
- **Test:** Unit tests for divergence calculation, source switching, self-healing

### B4: Cross-Check Sensor (Optional — defer if scope grows)

New diagnostic sensor: `sensor.ura_energy_source_divergence`
- State: divergence % between Envoy and utility meter
- Attributes: envoy_kwh, utility_kwh, emporia_kwh, divergence_envoy_utility, divergence_envoy_emporia

### Acceptance Criteria
- **Verify:** Sensor shows non-zero values when all three sources configured
- **Verify:** Sensor shows "unavailable" when utility meter not configured

## Files Modified

| File | Changes |
|------|---------|
| `energy_const.py` | `CONF_ENERGY_UTILITY_METER_ENTITY` |
| `config_flow.py` | Utility meter entity picker in energy step |
| `energy.py` | Read utility sensor, compute divergence, pass to CostTracker |
| `energy_billing.py` | Divergence tracking, prediction source switching, attributes |
| `sensor.py` | Add prediction_source/divergence attributes to predicted_bill sensor; optional B4 sensor |
| `database.py` | Populate `grid_import_2` in `log_energy_history()` |
| `strings.json` + `translations/en.json` | Labels |

## Risk Assessment

**MEDIUM risk because:**

**What's safe:**
- B1 (config flow) — follows existing pattern exactly, no logic changes
- B2 (grid_import_2) — simple read + store, column already exists, backwards compatible
- B4 (diagnostic sensor) — read-only, no side effects

**What needs care:**
- B3 (bill calibration) — most complex piece:
  - Reconciling two different cycle boundaries (utility vs URA billing cycle day) requires careful delta tracking
  - `total_increasing` sensors reset unpredictably — need to handle resets without interpreting them as huge consumption drops
  - Source switching affects `predicted_bill` which users rely on for financial decisions — wrong switch = bad predictions
  - The 3-day rolling average needs persistence across restarts (or accept cold-start delay)

**What could go wrong:**
- Utility sensor updates only daily — stale data could cause false divergence if compared against real-time Envoy data
- Utility sensor may lag by 1-2 days (depends on SmartHub scraping schedule)
- If utility sensor stops updating (integration breaks), divergence grows → false source switch

**Mitigation:**
- B3 should check utility sensor `last_changed` — if stale >48h, don't compute divergence
- Source switching should be gated behind the EV TOU management toggle or a new toggle
- Start with divergence reporting only (attributes), defer automatic source switching to a follow-up if the numbers prove stable

## Simplified Version (if MEDIUM risk is too high)

**B-Lite:** Do B1 + B2 + divergence attributes only. No automatic source switching. Just surface the divergence in sensor attributes so you can see it in the dashboard. Add source switching later once you trust the numbers.

This reduces risk to LOW — it's config + read + store + display, no behavioral changes.
