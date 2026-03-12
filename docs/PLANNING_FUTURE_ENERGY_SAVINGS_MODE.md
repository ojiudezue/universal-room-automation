# Future Energy Optimization — Savings Mode Exploration

**Status**: Exploration / Not Scheduled
**Date**: 2026-03-11
**Prerequisite**: energy_history data (Phase D of v3.11.0) — need real-world data to validate value proposition

---

## The Problem: Stranded Battery Capacity

In `self_consumption` mode, battery can only serve house load — never push to grid. During peak/mid-peak windows when solar is low, battery capacity beyond house load sits idle.

### Quantified Waste (Summer Peak Example)

| Metric | Value |
|---|---|
| Peak window | 4 hours (16:00-20:00) |
| Avg house load | ~2 kW |
| Battery discharge capacity | ~7.5 kW (8x IQ5P) |
| Battery energy covering load | 8 kWh × $0.162 = **$1.30** |
| Unused battery capacity | 5.5 kW × 4h = 22 kWh |
| Lost export revenue | 22 kWh × $0.162 = **$3.56** |
| **Daily gap** | **~$3.56** (summer), **~$1.38** (shoulder at $0.086) |
| **Monthly gap** | **~$107** (summer), **~$41** (shoulder) |

These are upper bounds — actual gap depends on solar production during peak (which covers some load itself), round-trip efficiency losses, and real house load variability.

### Shoulder/Winter Mid-Peak

Shoulder mid-peak: 17:00-21:00, $0.086/kWh. Same constraint applies — battery covers 2kW house load but can't export the other 5.5kW. We already discharge correctly (energy_battery.py:368-376), but `self_consumption` caps the value.

Winter mid-peak: 05:00-09:00 + 17:00-21:00, $0.086/kWh. Morning window is especially interesting — battery is draining overnight per our off-peak drain strategy, but if we could export remaining capacity during morning mid-peak before solar kicks in, that's additional revenue.

---

## The Hypothesis: Temporary Savings Mode

Switch to `savings` mode during peak/mid-peak windows to enable Enphase's battery-to-grid export, then switch back to `self_consumption` afterward.

### How Savings Mode Works

Per the Enphase codicil:
- Enphase's internal TOU optimizer decides when to discharge to grid
- TOU schedule configured **in the Enphase app**, not via HA
- HA loses real-time control of reserve level and discharge behavior
- Battery can export to grid (the key advantage)

### Proposed Strategy

```
Off-peak:  self_consumption  (HA controls drain/arbitrage/EVSE hold)
Mid-peak:  savings           (Enphase exports battery to grid)
Peak:      savings           (Enphase exports battery to grid)
Post-peak: self_consumption  (HA resumes control)
```

### Prerequisites

1. **Enphase TOU schedule must match PEC rates** — Configure the same TOU windows in the Enphase app. If they diverge, Enphase exports at wrong times.
2. **Mode switch latency budget** — 30-60 seconds per switch. Schedule 2 minutes before period boundary.
3. **energy_history data** — Need at least 30 days of `self_consumption` baseline to measure improvement.

---

## Risk Assessment

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Loss of HA control during peak** | HIGH | Can't adjust reserve if conditions change (clouds, unexpected load) |
| **Storm during savings window** | HIGH | Must monitor weather and abort switch if storm forecast appears |
| **Mode switch fails/slow** | MEDIUM | Enphase latency 30-60s; could miss window or overlap |
| **Enphase TOU schedule drift** | MEDIUM | If app schedule doesn't match PEC, exports at wrong rate |
| **Grid outage during savings** | LOW | Enphase handles this internally but behavior less predictable than backup |
| **Round-trip efficiency** | LOW | 95% — same whether we export via self_consumption or savings |
| **EVSE hold breaks** | MEDIUM | Our EVSE battery hold logic can't work in savings mode — Enphase decides discharge |

### Kill Switch

If any of these conditions are true, abort savings mode switch:
- Storm forecast active
- Grid connectivity issues (envoy unavailable count > 0 in last hour)
- EVSE actively charging (would drain battery uncontrolled in savings mode)
- SOC below 50% at window start (not enough to export meaningfully)

---

## Implementation Sketch (If Validated)

### Phase 1: Data Collection (No Code Changes)

Use energy_history + external_conditions data from v3.11.0 Phase D to calculate:
1. Actual house load during peak/mid-peak windows (hourly averages)
2. Actual battery SOC at window boundaries
3. Actual solar production during these windows
4. Theoretical export revenue if battery capacity were fully utilizable

**Decision gate**: If theoretical monthly gap > $30 (net of efficiency losses), proceed to Phase 2.

### Phase 2: Controlled Experiment

1. Add `CONF_ENERGY_SAVINGS_MODE_EXPERIMENT` toggle (default off)
2. On experiment days (e.g., alternating days), switch to savings mode during peak
3. Log actual export data via Envoy entities
4. Compare experiment days vs control days in energy_history
5. Run for 2 weeks minimum

### Phase 3: Production (If Experiment Positive)

1. Add savings mode window to battery strategy
2. Add kill switch conditions
3. Add pre-switch validation (SOC, weather, EVSE state)
4. Config flow: enable/disable, window customization
5. Sensor attributes: `savings_mode_active`, `savings_mode_abort_reason`

---

## What We Can't Do With Savings Mode

- **Fine-grained reserve control** — Enphase decides
- **EVSE battery hold** — Our hold logic is bypassed
- **Storm preparation** — Must abort savings and switch to backup
- **Arbitrage** — Enphase handles its own arbitrage; may conflict with ours
- **Off-peak drain targets** — Only work in self_consumption

---

## Alternative: Enphase API Direct Control

Enphase may add direct battery discharge commands in future firmware/API updates. The Enphase IQ Gateway (Envoy) has a local API that the HA integration uses. If direct export commands become available:

- We could stay in `self_consumption` mode permanently
- Issue discharge-to-grid commands during peak
- Maintain full HA control
- No mode switching needed

**Action**: Monitor Enphase firmware releases and HA integration changelogs for new capabilities.

---

## EVSE Config UI (Separate But Related)

Advanced EVSE management features from v3.11.0 should be exposed in the config flow UI as a future follow-up:

| Setting | Type | Default | Purpose |
|---|---|---|---|
| Advanced EVSE Management | Toggle | Off | Master enable for excess solar + battery hold |
| Excess Solar SOC Threshold | Number | 95% | SOC level to trigger excess solar EVSE charging |
| Excess Solar kWh Threshold | Number | 5.0 | Remaining forecast kWh to trigger |
| Battery Hold on EVSE Charge | Toggle | On (when EVSE mgmt enabled) | Hold battery when EVSEs are charging |
| Arbitrage Enabled | Toggle | Off | Enable grid charge arbitrage |
| Arbitrage SOC Trigger | Number | 30% | SOC below which arbitrage activates |
| Arbitrage SOC Target | Number | 80% | SOC target for arbitrage charging |
| Drain Target: Excellent | Number | 10% | Off-peak drain for excellent forecast |
| Drain Target: Good | Number | 15% | Off-peak drain for good forecast |
| Drain Target: Moderate | Number | 20% | Off-peak drain for moderate forecast |
| Drain Target: Poor | Number | 30% | Off-peak drain for poor forecast |

These are independent of the savings mode experiment and should ship in a near-term config flow update.

---

## Decision Timeline

1. **Now**: Deploy v3.11.0 with energy_history logging (Phase D)
2. **+30 days**: Analyze energy_history data to quantify actual gap
3. **+45 days**: If gap > $30/month, design Phase 2 experiment
4. **+75 days**: If experiment positive, implement Phase 3
