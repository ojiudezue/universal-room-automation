# Energy Coordinator — User Manual

**Device:** `URA: Energy Coordinator`
**Last updated:** 2026-05-11 (v4.5.11.3 baseline; v4.5.12 sensor additions to follow)
**Scope:** every control, sensor, switch, and form field on the Energy Coordinator surface

This is a task-oriented manual: skim the section headings to find what you need, read the troubleshooting recipes when something feels wrong. The reasoning behind each default is included so you can judge edge cases without re-deriving from first principles.

---

## 1. What the Energy Coordinator does

URA: Energy Coordinator is the brain that decides, every 5 minutes, how the house manages its battery, its grid imports, and its surplus solar. It runs six loosely-coupled subsystems under one decision cycle:

- **Battery Strategy** — the four-phase state machine (WAIT → CHARGE → HOLD → DISCHARGE) that arbitrages off-peak grid into peak displacement, with multi-day Solcast awareness and EV-charging mutual-exclusion
- **Time-of-Use Engine** — knows which TOU period and rate apply at every moment, including cross-midnight transitions and seasonal switching
- **Solar Forecast** — pulls Solcast (today + tomorrow + D+2) and classifies each day as excellent / good / moderate / poor / very_poor
- **EV Charge Controller** — gates EVSEs by TOU period, battery state, and arbitrage mutual-exclusion
- **HVAC Constraint** — feeds offsets and coast/shed/precool/preheat signals into the HVAC Coordinator so climate behavior adjusts to energy state
- **Load Shedding** — detects sustained grid imports above threshold and triggers reduction signals to other coordinators

All six share the same `EnergyData` snapshot (refreshed every cycle) and the same circuit-monitor (Span / Emporia / Sense — via the per-circuit integrations you configured). Each subsystem has a master kill-switch.

**Decision cadence:** 5-minute polling cycle, plus event-driven response to circuit-level anomalies, EVSE state changes, and Envoy availability transitions.

---

## 2. The four-phase battery state machine (v4.5.0)

This is the headliner. It replaced v3.11.0's SOC-trigger arbitrage that wasted off-peak charges.

```
                    ┌─────── chunk_completed ───────┐
                    │   (chunk = one off-peak run)  │
                    ▼                                │
  ┌──────┐   gate    ┌────────┐  SOC≥target  ┌──────┐  TOU enters peak/mid_peak
  │ WAIT │ ────────► │ CHARGE │ ───────────► │ HOLD │ ───────────────────────────┐
  └──────┘  opens    └────────┘              └──────┘                            │
     ▲                  ▲                                                       ▼
     │                  │ reverts if forecast improves               ┌─────────────────┐
     │  TOU enters      │ at first WAIT→CHARGE per chunk             │   DISCHARGE     │
     └─ off_peak ───────┴────────────────────────────────────────────│   (existing)    │
                                                                     │   reserve=10    │
                                                                     │   no grid chg   │
                                                                     └─────────────────┘
```

| Phase | When | Reserve SOC | Charge from grid | What it does |
|---|---|---|---|---|
| **WAIT** | Off-peak, before the charge window opens | 10 (reserve_soc) | OFF | Battery serves loads naturally. SOC drifts down. |
| **CHARGE** | Off-peak, charge window open, SOC < target, forecast still poor on recheck | 80 (peak_buffer_target) | **ON** | Grid charges the battery. **EV mutual-exclusion engages** — any EVSE that's running is paused for the duration. |
| **HOLD** | SOC reached target during CHARGE | 80 | OFF | Buffer locked at target. Solar can still push above 80%, but grid won't. Eliminates the v3.11.0 drain-back-down regression. |
| **DISCHARGE** | TOU enters mid_peak or peak | 10 | OFF | Battery covers load, displaces high-rate imports. Standard pre-v4.5.0 behavior. |

**Charge window timing:** `charge_start_time = next_high_rate_transition − arbitrage_charge_lead_time_min`. Default lead time is 360 min (6 hr). Biases toward earlier start so intraday Solcast updates (which accumulate from sunrise) can re-classify the target day. Hard min 120 min (physics floor + safety margin), hard max 720 min.

**Per-chunk lock:** one arbitrage cycle per off-peak chunk. Resets on TOU transition INTO off_peak. Prevents oscillation if SOC dips post-completion or the forecast wobbles.

**Forecast re-check:** at the first WAIT→CHARGE transition per chunk, the coordinator re-classifies the target day's solar forecast. If the forecast improved (e.g., poor → good), the cycle aborts — sets `chunk_completed=True` and stays in WAIT for the rest of the chunk. No wasted grid charge.

---

## 3. The kill-switches (master toggles)

Two switches live on the Energy Coordinator device.

### `Enabled`
**Default:** ON
**What it does:** master enable for the entire Energy Coordinator. When OFF, the decision cycle still runs (and records measurements for sensors) but issues **no commands** to Envoy, EVSEs, or HVAC. All actuation paths short-circuit.
**When to disable:** during major utility-meter events, hardware swaps, or whole-house diagnostic sessions where you want URA's sensors to keep observing but not act.

### `Observation Mode`
**Default:** OFF
**What it does:** softer than `Enabled = OFF`. The coordinator still computes decisions but **stops actuating Enphase storage mode + reserve SOC + charge-from-grid**. EVSE controls and HVAC constraints continue to flow. Useful for confirming the strategy matches your intuition before letting it commit.
**When to enable:** first 1–2 weeks after major config changes (new TOU schedule, new Solcast credentials, new arbitrage settings) so you can verify the *intent* of every decision before it touches your battery.

### `EV TOU Management` — strict policy behavior (v4.7.x)
**Default:** ON
**What it does:** when ON, URA pauses all EVSEs during peak and mid_peak TOU periods. **This is a strict, idempotent policy** — if you manually re-enable an EVSE switch in HA, URA will turn it off again on the next decision cycle (≤5 min). Manual HA-side EVSE toggles are intentionally defeated.
**Rationale:** "All grid charging for EV should happen only during off-peak for every season." The strict enforcement prevents cost leaks caused by accidental or casual EVSE re-enables during high-rate periods.
**Exception:** excess-solar charging (when battery ≥95% and solar forecast surplus ≥5 kWh) is still allowed during mid_peak — the switch is ON and URA leaves it running.
**Admin override:** use `button.ura_energy_coordinator_evse_force_charge_30min` for intentional mid-peak charging (see §10 below).

Master gating order — **strict precedence**:

```
1. Envoy unavailable        → hold state, no commands fire
2. Grid disconnected         → BACKUP storage mode
3. Storm forecast active     → BACKUP / pre-charging (storm wins over arbitrage)
4. Peak / mid_peak TOU       → DISCHARGE logic
5. Off-peak                  → arbitrage phase OR drain-target fallback
```

Don't re-order these in custom automations layered on top — the precedence prevents combinations like "BACKUP + arbitrage charge" that would fight each other.

---

## 4. Runtime sliders (Number entities)

Every Number entity on the Energy Coordinator device is **runtime-tunable** — change the slider value and the next decision cycle picks it up. No reload needed. The slider's value survives HA restart (RestoreEntity-backed). Form-level CONF values are install-time seeds only.

### `Peak Buffer Target` — 30–95%, default 80%
The SOC target that arbitrage CHARGE drives to. Higher means more buffer for peak displacement but more grid imports during off-peak; lower means less stress on the grid but smaller peak coverage.
**Raise** for higher-cost peak periods where every extra kWh of buffer pays back.
**Lower** if you're frequently hitting the grid-import guard during CHARGE or if utility export rates make holding a smaller buffer more economical.
**Note:** values below 30% defeat the purpose (battery won't cover meaningful peak load). Values above 95% stress the battery and rarely complete in time.

### `Arbitrage Charge Lead Time` — 120–720 min, default 360 min (6 hr)
How early (before the next high-rate transition) the charge window opens. Earlier means more time to absorb intraday Solcast updates and adjust; later means less off-peak grid energy spent on a forecast that might still change.
**Raise** if you frequently see arbitrage abort mid-CHARGE because forecast improved. Earlier lead time biases the re-check before commitment.
**Lower** if you observe CHARGE running deep into the high-rate window (rare — usually means the lead time is wrong or grid-import guard is throttling).
**Why `NumberMode.BOX` not slider:** minute-precision values are easier to type than drag. Single decision-cycle worth of granularity matters.

### `Off-Peak Drain Excellent` / `Good` / `Moderate` / `Poor` — 5–80% (per slider), defaults 10 / 15 / 20 / 30
The SOC drain target during off-peak hours, by solar day class. When the next day's solar forecast classifies as excellent, the battery is allowed to drain lower (because tomorrow's PV will refill it for free); on poor days the drain target stays higher so tomorrow's peak still has coverage.
**Tune by climate:** in summer with consistent solar, lower drain targets across the board. In winter with variable solar, raise them.
**One slider per day class** — four sliders. Set them in order of aggression (excellent < good < moderate < poor) or arbitrage logic will warn.

### `EV Battery Drain SOC` — 30–80%, default 50%
The SOC floor at which EV charging from house battery is allowed to start consuming battery (versus pulling from grid). Lower means "fill the EV from battery as long as battery has more than X%"; higher means "preserve the house battery, charge the EV from grid only."
**Raise** if you have a small house battery and a large EV — protects house from being drained by EV.
**Lower** if you have generous PV + storage and want to maximize self-consumption.

---

## 5. Form fields (configured once, at install)

These are set in **Coordinator Manager → Energy** at install time. Most are entity-pickers pointing at your hardware integrations. Changing them requires a reload to take effect.

### Required hardware sensors
| Field | What to set it to |
|---|---|
| **Solar Production Entity** | Enphase Envoy production sensor in kW (e.g., `sensor.envoy_current_power_production`) |
| **Net Power Entity** | Whole-house net kW (positive = importing from grid; negative = exporting) |
| **Battery SOC Entity** | Battery state-of-charge sensor in % (e.g., `sensor.enpower_battery_soc`) |
| **Battery Power Entity** | Battery charge/discharge kW |
| **Grid Import Sensor** / **Grid Export Sensor** | Cumulative kWh totalizers from your utility meter or Envoy |
| **Envoy Entity** | The Enphase Envoy gateway device entity (used as availability proxy) |
| **Lifetime Consumption / Production / Net Import / Net Export / Battery Charged / Battery Discharged** | Six lifetime-cumulative kWh sensors for billing accuracy and arbitrage savings math |

### Solcast forecast
| Field | What to set it to |
|---|---|
| **Solcast Today Entity** | `sensor.solcast_pv_forecast_forecast_today` (typical) |
| **Solcast Remaining Entity** | `sensor.solcast_pv_forecast_forecast_remaining_today` |
| **Solcast Tomorrow Entity** | `sensor.solcast_pv_forecast_forecast_tomorrow` |
| **Solcast Day 3 Entity** *(optional, v4.5.0+)* | `sensor.solcast_pv_forecast_forecast_day_3` — enables D+2 awareness |
| **Solar Classification Mode** | `percentile` (recommended; uses month-aware thresholds) or `fixed` |
| **Solar Threshold Excellent / Good / Moderate / Poor** | The kWh-per-day boundaries between classes. Defaults track your local climate's percentiles. |

### EV / EVSE
| Field | What to set it to |
|---|---|
| **EVSE A Entity** / **EVSE B Entity** | Switch or input_boolean controlling each charger (Enphase IQ EV, Wallbox, etc.) |
| **L1 Charger Entities** | List of low-power EV chargers that don't trigger mutual-exclusion |

### Optional
| Field | What to set it to |
|---|---|
| **Weather Entity** | Used for storm-forecast detection (BACKUP precedence rule) |
| **Generator Entity** | If you have one — used for backup-runtime calculations |
| **Utility Meter Entity** | If your utility provides a smart-meter integration separate from Envoy |
| **TOU Rate File** | Path to your utility's TOU schedule JSON (lives in `/config/`) |

### Load shedding
| Field | What to set it to |
|---|---|
| **Load Shedding Enabled** | Master toggle for the shed signal to HVAC + other coords |
| **Load Shedding Threshold (kW)** | Grid-import kW that triggers shed (default 12 kW — sized for a 60A DER breaker) |
| **Load Shedding Sustained Minutes** | How long the import must exceed threshold before shed fires (default 5 min) |
| **Load Shedding Mode** | `advisory` (sensor only) or `actuate` (broadcasts shed signal) |

### HVAC constraint offsets
The HVAC Coordinator reads these to know how aggressively to coast / precool / preheat based on energy state.
| Field | Default | Effect |
|---|---|---|
| **Coast Offset** | +1.5°F | When coasting (high battery, excess solar), let setpoints drift this much |
| **Pre-Cool Offset** | −1.5°F | When pre-cooling for forecasted peak, drop setpoints by this much |
| **Pre-Heat Offset** | +1.5°F | Symmetric for heating |
| **Shed Offset** | +3.0°F | When load shedding fires, widen setpoints by this much |
| **Pre-Heat Temp Threshold** | 35°F | Forecast-low below which pre-heat fires |

### Arbitrage
| Field | What it does |
|---|---|
| **Arbitrage Enabled** | Master for the four-phase state machine |
| **Multi-Day Horizon Enabled** | When ON, gate also fires on D+2 poor forecasts (v4.5.0 default OFF until calibrated) |
| **Grid Import Guard kW** | Hard cap on grid import during CHARGE (default 12 kW, was 20 before v4.5.0.3) |
| **Excess Solar Enabled / SOC / kWh** | Routes surplus solar above the SOC threshold to other loads (heat pump, hot water, thermal banking) when daily kWh budget allows |

---

## 6. Sensors — what to watch

The Energy Coordinator device hosts 40+ sensors. These are the ones to put on a dashboard:

### Daily snapshots
- **`Battery Strategy`** — current 4-phase state (WAIT / CHARGE / HOLD / DISCHARGE / BACKUP). The single most important signal for "what is the battery doing right now?"
- **`Solar Day Class`** — today's and tomorrow's class (excellent / good / moderate / poor / very_poor). Drives drain targets and the arbitrage gate.
- **`TOU Period`** — current period (off_peak / mid_peak / peak). Use this for automations.
- **`TOU Rate`** — current $/kWh.
- **`Current Rate`** / **`Delivery Rate`** — the rate URA used in the last cost calculation (sanity check).
- **`Situation`** — high-level state machine label combining energy state + occupancy state (used by HVAC).

### Today + cycle accounting
- **`Energy Import Today`** / **`Energy Export Today`** — kWh totals reset at midnight.
- **`Cost Today`** / **`Cost Cycle`** — dollar totals (daily, billing-cycle).
- **`Predicted Bill`** — current month's bill prediction based on consumption pace + rate schedule.

### Forecast + accuracy
- **`Forecast Today`** / **`Forecasted Import`** / **`Forecasted Consumption`** — what the day is expected to look like.
- **`Forecast Accuracy`** — rolling 30-day comparison of forecast vs actual. Calibration signal.
- **`Battery Full Time`** — estimated time-of-day when battery will hit 100% (or "not today" if not).

### Arbitrage savings
- **`Arbitrage Savings Today`** / **`...Cycle`** / **`...Total`** — estimated $ saved by arbitraging off-peak → peak. Counterfactual: charge_kWh × (peak_rate − off_peak_rate) × round_trip_efficiency.

### EV + circuits
- **`EV Charging Status`** — per-EVSE state (idle / charging / paused_by_arbitrage / paused_by_tou / paused_by_grid_cap).
- **`EV Charge Rate A`** / **`EV Charge Rate B`** — live A/B charger output.
- **`Circuit Anomaly`** — z-score detection on each Span/Emporia circuit. Surface as a notification target.

### Diagnostics
- **`Battery Decision`** — the most recent decision-cycle reason text. Read this to understand why the battery is in its current state.
- **`Load Shedding`** — current shed level (0–3) and reason.
- **`Envoy Status`** — Enphase availability + last-known communication time.
- **`Pool Optimization`** — pool-pump schedule optimization status (if you have one).
- **`Generator Status`** — backup runtime + fuel estimate.

---

## 7. Three-layer gating model

The same shape used elsewhere in URA:

```
┌──────────────────────────────────────────────────────────────┐
│  Master switch (Enabled, Observation Mode)                   │
│    ↓ OFF/Observation → no actuation                          │
│    ↓ ON → evaluate next layer                                │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│  Feature toggles (Arbitrage Enabled, Load Shedding Enabled,  │
│  Excess Solar Enabled, Multi-Day Horizon, Grid Import Cap…)  │
│    ↓ OFF → that subsystem skipped                            │
│    ↓ ON → evaluate per-decision logic                        │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│  Per-decision gates                                          │
│    ↓ (TOU period, SOC, forecast class, storm, Envoy avail…)  │
│    ↓ All gates pass → command fires                          │
└──────────────────────────────────────────────────────────────┘
```

---

## 8. Troubleshooting

### "Arbitrage charged but battery drained back down before peak"

This was the v3.11.0 bug v4.5.0 fixed. If it's still happening on v4.5.0+:
1. Confirm you're on v4.5.0 or later: `sensor.ura_universal_room_automation` or the integration's About page.
2. Check **Battery Strategy** sensor: was the state HOLD between CHARGE end and mid_peak start? If not, see #2 below.
3. Off-peak drain target may be too low. Look at the day class — if classified as "excellent" but the drain slider for excellent is set to 5%, the battery will drain even from HOLD via natural load. Raise the slider.

### "Arbitrage CHARGE never fires when it should"

1. Confirm **Arbitrage Enabled** switch is ON.
2. Check **Solar Day Class** sensor — the gate only opens when target day classifies as `poor` or `very_poor` (or D+2 with Multi-Day Horizon ON).
3. Check **Arbitrage Charge Lead Time** — if too short, the charge window may never have opened before the high-rate transition arrived.
4. Check **Battery Decision** sensor — it logs the gate reason ("forecast improved on recheck" / "chunk_completed" / "Envoy unavailable" / etc.).
5. Per-chunk lock: only one arbitrage cycle per off-peak chunk. If the chunk completed earlier, the next attempt won't fire until TOU re-enters off_peak.

### "EV stopped charging unexpectedly during off-peak"

Most likely the arbitrage mutual-exclusion paused it during CHARGE phase.
1. Check **EV Charging Status** sensor — if it says `paused_by_arbitrage`, that's the cause.
2. Check **Battery Strategy** sensor — was the state CHARGE during the pause?
3. EV will resume automatically when battery hits HOLD or DISCHARGE.
4. To opt out: temporarily disable **Arbitrage Enabled** for that off-peak chunk. The EV will resume immediately.

### "Cost Today seems way off vs my utility bill"

1. Confirm **TOU Rate File** is current — utility rate plans change.
2. Check **Forecast Accuracy** sensor — if it's been drifting for >2 weeks, the consumption model may be miscalibrated.
3. Lifetime sensor consistency: divergence between Envoy "today" and URA's lifetime-delta indicates a snapshot stale-ness issue, logged as a WARNING. Common after Envoy reboots — usually self-corrects within 24 hr.
4. Verify your **Delivery Rate** matches your utility's posted delivery charge. URA's `delivery_rate` is a separate slider from the energy rate.

### "Solar Day Class always says 'moderate' even on sunny days"

1. Confirm **Solcast** entities are populated (not `unavailable`). Solcast occasionally rate-limits or expires API keys.
2. Check **Solar Classification Mode** — if set to `fixed`, the thresholds might be wrong for your kW system. Switch to `percentile` for month-aware classification.
3. Solar Thresholds (Excellent / Good / Moderate / Poor) should match the seasonal kWh ranges of your PV system. Use 30 days of historical production data to calibrate.

### "Excess solar isn't routing anywhere even though I'm exporting kWh"

1. Confirm **Excess Solar Enabled** is ON.
2. Check **Excess Solar SOC** — surplus routing only fires above this SOC (default 95%). Below threshold, surplus charges the battery instead.
3. Check **Excess Solar kWh** — daily budget. If exhausted, routing pauses until midnight rollover.
4. Look at the destination — the heat pump / pool pump / thermal-banking target must be configured separately (not part of EC; lives in HVAC or pool integrations).

### "Load shedding never fires even when I see big grid imports"

1. Confirm **Load Shedding Enabled** is ON.
2. Confirm **Load Shedding Mode** is `actuate` (not `advisory` — advisory only updates the sensor without broadcasting).
3. Check **Load Shedding Threshold** — sustained ≥ threshold for `Sustained Minutes` is required. A 10-second spike won't trigger.
4. Look at the **Load Shedding** sensor — it logs `imports_above_threshold_for=X.Xmin` so you can see how close you are.

### "Observation Mode is on but the battery still changes mode"

Observation Mode stops **actuation** to Enphase's storage_mode / reserve_soc / charge_from_grid. It does NOT stop:
- TOU-driven battery behavior (which Enphase manages locally based on its own profile)
- EV controls (these still fire — to fully pause, disable `Enabled`)
- HVAC constraints (these still flow — HVAC offsets and shed/coast/precool/preheat signals continue)

If you want **everything** paused, set the master `Enabled` switch to OFF.

---

## 9. Reading the activity log

`/config/universal_room_automation/data/universal_room_automation.db` table `ura_activity_log` records significant EC decisions. Filter by `coordinator='energy'`:

```sql
SELECT
  timestamp, action, importance, description, details_json
FROM ura_activity_log
WHERE coordinator = 'energy'
  AND timestamp > datetime('now', '-1 day')
ORDER BY id DESC;
```

Common action types:
- `arbitrage_phase_transition` — WAIT→CHARGE→HOLD→DISCHARGE transitions
- `arbitrage_gate_open` / `arbitrage_gate_closed` — gate state changes
- `arbitrage_chunk_completed` — per-chunk lock fired
- `arbitrage_forecast_recheck` — forecast re-classified on first WAIT→CHARGE
- `ev_paused_by_arbitrage` / `ev_resumed` — mutual-exclusion events
- `storage_mode_change` / `reserve_soc_change` / `charge_from_grid_change` — direct Enphase commands
- `load_shedding_engaged` / `load_shedding_cleared`
- `excess_solar_routed` — surplus diversion events
- `tou_transition` — off_peak ↔ mid_peak ↔ peak boundaries

`details_json` contains decision context (SOC, forecast values, calculated savings) for each event.

---

## 10. Architecture sketch (decision flow per cycle)

Every 5 minutes, the Energy Coordinator does, in order:

1. **Snapshot inputs** — pull current SOC, net power, solar, all six lifetime sensors, Solcast (today + tomorrow + D+2 if configured), Envoy availability, TOU period + rate.
2. **Day-rollover check** — if new date, reset daily counters, recalculate solar percentile thresholds, refresh predicted-bill counterfactual baseline.
3. **Strict precedence** — evaluate the five precedence rules from §3 in order.
4. **Battery strategy** — if precedence selects "off-peak arbitrage", determine WAIT / CHARGE / HOLD via gate + per-chunk lock + forecast re-check. Otherwise apply drain-target fallback.
5. **EV mutex** — if battery phase is CHARGE, pause EVSEs into `_paused_by_arbitrage`. Otherwise release (subject to other pause reasons).
6. **HVAC constraint** — compute current offsets (coast / precool / shed) and dispatch `energy_constraint_mode` to HVAC.
7. **Load shedding** — check grid import vs threshold over sustained window; fire signal if exceeded.
8. **Excess solar routing** — if SOC > threshold AND daily kWh budget allows, route surplus to configured destinations.
9. **Update sensors** — write fresh values to every dashboard sensor.
10. **Persist decision** — append to `ura_activity_log` if significant; update `arbitrage_cycles` if a charge cycle started/completed.

Each step is idempotent. Running it twice produces the same state. Race-safe across HA restarts.

---

## 11. Architecture sketch (arbitrage / EV mutual-exclusion)

The compound-load case (20 kW battery charge + 7.4 kW EV + 5 kW house base = ~134A on main breaker) is the panel-stress scenario v4.5.0 D4 prevents.

```
                      arbitrage_phase
                            │
                ┌───────────┴────────────┐
                │                        │
              CHARGE                   not CHARGE (WAIT/HOLD/DISCHARGE)
                │                        │
                ▼                        ▼
   ┌──────────────────────┐    ┌────────────────────────┐
   │ For each EVSE:       │    │ For each EVSE:         │
   │   if running:        │    │   if in _paused_by_   │
   │     turn_off()       │    │     _arbitrage set:    │
   │     add to           │    │       check other      │
   │     _paused_by_arb   │    │       pause reasons    │
   │   if not running:    │    │       (grid_cap,       │
   │     proactively      │    │        battery_drain)  │
   │     claim slot       │    │       if none → resume │
   │     so plug-in       │    │       remove from set  │
   │     can't start      │    │                        │
   └──────────────────────┘    └────────────────────────┘
```

The `_paused_by_<reason>` set + precedence-rule pattern is the same architecture v4.7.x will copy onto appliance controllers (LG ThinQ, Rainbird).

---

## 12. Related entities (not on this device but relevant)

- **HVAC Coordinator** — reads `energy_constraint_mode` from EC. See `docs/user-manual/HVAC_COORDINATOR.md` for how HVAC responds to coast / shed / precool / preheat.
- **Notification Manager** — fires alerts for major EC events (storm forecast, prolonged Envoy unavailability, arbitrage savings milestones).
- **Span Panel integration** — provides per-circuit power sensors used by the Circuit Anomaly detector.
- **Solcast PV Forecast integration** — provides the day-ahead solar forecasts that drive day classification.
- **Enphase Envoy integration** — the actuation surface (storage_mode / reserve_soc / charge_from_grid switches).

---

## Appendix: full entity list (URA: Energy Coordinator device)

### Sensors (daily snapshots & strategy)
| Entity ID | Purpose |
|---|---|
| `sensor.ura_energy_coordinator_battery_strategy` | 4-phase state machine label (WAIT / CHARGE / HOLD / DISCHARGE / BACKUP) |
| `sensor.ura_energy_coordinator_solar_day_class` | Today + tomorrow forecast class |
| `sensor.ura_energy_coordinator_tou_period` | Current TOU period |
| `sensor.ura_energy_coordinator_tou_rate` | Current $/kWh |
| `sensor.ura_energy_coordinator_tou_season` | Current TOU season (summer / winter) |
| `sensor.ura_energy_coordinator_current_rate` | Rate used in latest cost calc |
| `sensor.ura_energy_coordinator_delivery_rate` | Delivery rate |
| `sensor.ura_energy_coordinator_situation` | High-level energy + occupancy state |
| `sensor.ura_energy_coordinator_hvac_constraint` | Constraint mode signal to HVAC |

### Sensors (today / cycle / forecast)
| Entity ID | Purpose |
|---|---|
| `sensor.ura_energy_coordinator_energy_import_today` | Today's grid import kWh |
| `sensor.ura_energy_coordinator_energy_export_today` | Today's grid export kWh |
| `sensor.ura_energy_coordinator_cost_today` | Today's $ cost |
| `sensor.ura_energy_coordinator_cost_cycle` | Billing cycle $ cost |
| `sensor.ura_energy_coordinator_predicted_bill` | Current month bill prediction |
| `sensor.ura_energy_coordinator_total_consumption` | All-time consumption |
| `sensor.ura_energy_coordinator_net_consumption` | All-time net (consumption − production) |
| `sensor.ura_energy_coordinator_forecast_today` | Solcast PV forecast today |
| `sensor.ura_energy_coordinator_forecasted_import` | Forecast grid import |
| `sensor.ura_energy_coordinator_forecasted_consumption` | Forecast load consumption |
| `sensor.ura_energy_coordinator_battery_full_time` | Estimated SOC=100% time |
| `sensor.ura_energy_coordinator_forecast_accuracy` | 30-day rolling forecast accuracy |

### Sensors (arbitrage savings)
| Entity ID | Purpose |
|---|---|
| `sensor.ura_energy_coordinator_arbitrage_savings_today` | Today's est. savings |
| `sensor.ura_energy_coordinator_arbitrage_savings_cycle` | Cycle est. savings |
| `sensor.ura_energy_coordinator_arbitrage_savings_total` | Cumulative savings |

### Sensors (EV / circuits / diagnostics)
| Entity ID | Purpose |
|---|---|
| `sensor.ura_energy_coordinator_ev_charging_status` | Per-EVSE state |
| `sensor.ura_energy_coordinator_ev_charge_rate_a` / `_b` | Live A/B charger output |
| `sensor.ura_energy_coordinator_circuit_anomaly` | Per-circuit z-score anomaly detector |
| `sensor.ura_energy_coordinator_battery_decision` | Last decision-cycle reason text |
| `sensor.ura_energy_coordinator_load_shedding` | Current shed level (0–3) + reason |
| `sensor.ura_energy_coordinator_envoy_status` | Enphase availability + last comm |
| `sensor.ura_energy_coordinator_pool_optimization` | Pool pump schedule status |
| `sensor.ura_energy_coordinator_generator_status` | Backup runtime + fuel estimate |
| `sensor.ura_energy_coordinator_mode` | Coord mode + full attributes dump |

### Switches
| Entity ID | Purpose |
|---|---|
| `switch.ura_energy_coordinator_enabled` | Master — actuation kill |
| `switch.ura_energy_coordinator_observation_mode` | Compute + record but don't actuate |

### Number sliders
| Entity ID | Default | Purpose |
|---|---|---|
| `number.ura_energy_coordinator_peak_buffer_target` | 80% | SOC target during CHARGE |
| `number.ura_energy_coordinator_arbitrage_charge_lead_time` | 360 min | Charge window opens this far before high-rate transition |
| `number.ura_energy_coordinator_off_peak_drain_excellent` | 10% | Drain target on excellent solar day |
| `number.ura_energy_coordinator_off_peak_drain_good` | 15% | Drain target on good solar day |
| `number.ura_energy_coordinator_off_peak_drain_moderate` | 20% | Drain target on moderate solar day |
| `number.ura_energy_coordinator_off_peak_drain_poor` | 30% | Drain target on poor solar day |
| `number.ura_energy_coordinator_ev_battery_drain_soc` | 50% | SOC below which EV won't draw from house battery |

---

---

## 10. Admin override: EVSE force-charge button (v4.7.x)

### Why a button, not a switch?
A switch is a one-finger swipe — too easy to hit accidentally and leave active. A button + notification + audit trail is the "deliberate action" pattern. The button represents an explicit, time-bounded admin decision.

### `button.ura_energy_coordinator_evse_force_charge_30min`
**Entity:** `button.ura_energy_coordinator_evse_force_charge_30min`
**Device:** URA: Energy Coordinator

**What it does when pressed:**
1. Opens a 30-minute force-charge window during which URA's TOU pause is bypassed for all EVSEs.
2. Fires an NM info notification: `"EV force-charge window opened until HH:MM. Mid-peak rates apply."` (suppressed if observation mode is active).
3. Logs the activation with the UTC expiry timestamp.

**Auto-expiry:** the window expires automatically after 30 minutes. On the next decision cycle after expiry, URA resumes enforcing strict TOU pause. No manual cancellation needed — just wait.

**Idempotent re-press:** pressing the button while an override is already active replaces the window (30 min from now), not adds to it. Prevents accidental stacking.

**Override visibility:** `switch.ura_energy_coordinator_ev_tou_management` gains an `override_active_until_iso` attribute that shows the current window's UTC expiry (or `null` when inactive). Check this from Developer Tools → States to confirm the override is active.

**No HA-side bypass:** enabling the EVSE switch directly in HA while TOU is mid_peak/peak is still defeated by URA within ≤5 min (D1 strict enforcement). The force-charge button is the only supported override path.

**When to use:** intentional mid-peak EV charging (guest visiting, departure imminent, grid event). Not for routine off-peak charging — that happens automatically.

---

**See also:**
- `docs/user-manual/HVAC_COORDINATOR.md` — the climate side of the same brain
- `docs/readmes/README_v4.5.0.md` — the v4.5.0 battery-strategy redesign cycle (canonical reference)
- `docs/QUALITY_CONTEXT.md` — bug-class catalog (#1–#38) that reviews check against
