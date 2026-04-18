# v4.2.0 — B4 Layer 3: Energy Intelligence + Config Cleanup + Infrastructure Rooms

**Date:** April 18, 2026
**Scope:** B4 Energy Integration Layer 3, energy config cleanup, infrastructure room designation, circuit monitor configurability, config save error fix
**Tests:** 1478 passing (no regressions)

## Summary

Completes B4 (Bayesian Energy Integration) with 5 energy intelligence sensors,
configurable circuit monitoring, infrastructure room classification, and a
significant energy config cleanup that removes 6 dead configuration fields.

## What Changed

### Part A: Energy Config Cleanup

**Problem:** The integration-level "Energy Tracking Setup" page had 6 fields that
were configured by users but never read by any code — completely dead. Users
wasted time setting grid import sensors, battery level sensors, and rate fields
that did nothing. All were superseded by the Envoy auto-derivation on the Energy
Coordinator config or by TOU rate files.

**Removed fields:**
- Solar Export Sensor
- Grid Import Sensor (Primary)
- Grid Import Sensor (Secondary)
- Battery Level Sensor
- Delivery Rate ($/kWh)
- Export Reimbursement Rate ($/kWh)

**Kept fields (with improved labels):**
| Old Label | New Label |
|---|---|
| Whole House Power Sensors | Whole House Power (Total Consumption) |
| Whole House Energy Sensors | Whole House Energy (Total Daily kWh) |
| House Device Power Sensors | Standalone Device Power (EV, Pool, Water Heater) |
| House Device Energy Sensors | Standalone Device Energy (EV, Pool, Water Heater) |

**Backward compatibility:** The config constants are NOT deleted — existing stored
configs with these keys still load without error. Only the UI fields are removed
so new users don't see them.

**What goes where:**
- **Whole House Power/Energy** — Main panel CTs measuring total home consumption
  (e.g., SPAN mains, Emporia mains). Used for the attribution model (coverage delta).
- **Standalone Device Power/Energy** — Individual high-draw devices NOT assigned to
  rooms or zones (EV chargers, pool pumps, water heaters). These are "Tier 3" in
  the 4-tier energy attribution model.
- **Zone Power/Energy** — HVAC circuits and shared zone loads. Configured on the
  Zone Manager entry under each zone's "Zone Energy" step.
- **Room Power/Energy** — Per-room plugs, circuits, Shelly EMs. Configured on each
  room's "Energy" options step.

### Part B: Infrastructure Room Designation

Rooms with always-on equipment (networking gear, servers, AV equipment) need
special treatment. Without this, energy waste detection would constantly flag
them as "wasting energy" when they're simply doing their job.

**Two controls:**
1. **Room type dropdown** — New option "Infrastructure (Always-On Equipment)" in
   Basic Setup. Sets the initial infrastructure flag.
2. **Toggle switch** — `switch.{room}_infrastructure` visible on every room device
   card. Entity category CONFIG. Persists across restarts via RestoreEntity.

The toggle overrides the room type — a closet with a server gets the toggle ON
regardless of its room type. Default: ON for rooms with type "Infrastructure",
OFF for all others.

**Infrastructure rooms currently:** AV Closet, Media Closet, Study A Closet.

**How to set up:**
1. Go to the room's device card in HA
2. Find the "Infrastructure Room" switch under Configuration
3. Toggle ON
4. The room will appear in D6's infrastructure baseline (not waste) and be
   excluded from D7's cost-per-hour rankings

### Part C: Circuit Monitor Configurability

**Problem:** Circuit monitoring was hardcoded to auto-discover `sensor.span_panel_*_power`
entities. Emporia circuit sensors were invisible. Users with Shelly EMs, Iotawatt,
or other circuit monitors had no way to include them.

**What is SPAN Auto-Discover?** URA has always scanned for SPAN panel circuit entities
at startup by looking for sensors matching the pattern `sensor.span_panel_*_power`.
It filters out aggregate sensors (current_power, feed_through_power), and skips
breaker slots labeled "unknown", "unfilled", "unused", "spare", or "empty". Each
discovered circuit gets anomaly monitoring (z-score based), power baseline tracking,
and energy accumulation. This toggle preserves that existing behavior while making
it optional for users who don't have SPAN panels.

**New configuration (Energy Coordinator options):**

| Field | Purpose |
|---|---|
| **Additional Circuit Sensors** | Multi-select power sensor picker. Add Emporia channel sensors, Shelly EMs, Emporia balance sensors, or any power sensor you want monitored as a circuit. These merge with auto-discovered circuits. |
| **Auto-Discover SPAN Circuits** | Boolean, default ON. When ON, URA scans for `sensor.span_panel_*_power` at startup (existing behavior). Turn OFF if you don't have SPAN panels. |
| **Generator Status Entity** | Optional entity picker. Replaces the hardcoded Generac generator status sensor. Set this if you have a different generator. |
| **Grid Import Sensor (Direct)** | Optional power sensor for direct grid import measurement (e.g., Emporia `mains_from_grid`). When configured, used as the PRIMARY source for cost tracking instead of deriving from Envoy net power. More accurate. |
| **Grid Export Sensor (Direct)** | Optional power sensor for direct grid export measurement (e.g., Emporia `mains_to_grid`). Paired with the import sensor above. |

**How to set up circuit monitoring:**
1. Go to Settings > Devices > URA: Coordinator Manager > Configure
2. Select "Energy" from the menu
3. Scroll to the circuit section (near the bottom)
4. **For Emporia:** Add your Emporia channel power sensors to "Additional Circuit
   Sensors". Include the balance/unmeasured sensor if you want full sub-panel visibility.
5. **For Shelly EM:** Add the Shelly power sensor entities.
6. **For grid accuracy:** Set the Emporia `mains_from_grid` and `mains_to_grid`
   sensors as Grid Import/Export. This gives you meter-level accuracy for cost
   tracking instead of relying on Envoy's derived net power.
7. Save. Circuits will be discovered on next energy cycle (~5 min).

**How circuit sources merge:**
- SPAN auto-discovered circuits (if toggle ON)
- Manually-added circuit sensors (Additional Circuit Sensors picker)
- All deduplicated by entity_id — no double-counting

### Part D: Config Flow Save Error Fix

**Problem:** 7 out of 10 room option steps (sensors, devices, climate, sleep
protection, music following, energy, notifications) lacked error handling around
the config save operation. When a save triggered a background reload that took
too long, the UI showed "unknown error" even though the save succeeded.

**Fix:** Added try-except with debug logging to all 7 steps, matching the pattern
already used by `async_step_basic_setup`. The debug log shows:
```
step_name save: entry_id=..., merged_keys=...
```
This helps diagnose any future save issues.

### Part E: Layer 3 Energy Intelligence Sensors

Five new aggregation-level sensors on the integration device. All update every
30 seconds with the aggregation cycle.

#### D6: Energy Waste Idle
**Entity:** `sensor.universal_room_automation_energy_waste_idle`
**Unit:** W (watts)

Total power being drawn by rooms that are currently vacant (excluding
infrastructure rooms). Helps identify devices left on in empty rooms.

**Attributes:**
- `waste_rooms` — List of `{room, watts}` for vacant rooms drawing >5W
- `infrastructure_baseline` — List of `{room, watts}` for infrastructure rooms
  (reported as informational, NOT flagged as waste)
- `waste_room_count`, `infrastructure_room_count`
- `estimated_daily_waste_kwh` — If this waste persisted 24h, how many kWh

**How to use:** Create an automation that notifies you when waste exceeds a
threshold (e.g., >200W for >15 minutes). Check the `waste_rooms` attribute to
see which rooms are the culprits.

#### D7: Energy Cost Per Occupied Hour
**Entity:** `sensor.universal_room_automation_energy_cost_per_occupied_hour`
**Unit:** USD/h

How much it costs per hour when rooms are occupied. Computed as total energy
cost today divided by total occupied-hours across all non-infrastructure rooms.

**Attributes:**
- `rooms` — Per-room breakdown: `{room, cost_today, occupied_hours, cost_per_hour}`
  sorted by cost descending. Infrastructure rooms excluded.
- `most_expensive_room`, `most_efficient_room`

**How to use:** Track this over time to see efficiency trends. The per-room
breakdown in attributes shows which rooms cost the most to occupy.

#### D8: Energy Anomaly
**Entity:** `binary_sensor.universal_room_automation_energy_anomaly`
**Device class:** problem

Turns ON when any room draws significantly more power than its learned baseline
for the current time of day. Uses L1 power profiles (always learning — does NOT
require the L2 occupancy-weighted toggle to be ON).

**Detection logic:**
- Compares current room power against learned EMA baseline for (time_bin, day_type)
- Occupied rooms: threshold is 3x baseline (more variability expected)
- Vacant rooms: threshold is 2x baseline (should be near standby)
- Requires 20+ samples in the power profile (about 2 days of data)
- Ignores rooms drawing <10W (trivial loads)

**Attributes:**
- `anomalies` — List of `{room, current_watts, expected_watts, ratio, is_occupied}`
- `anomaly_count`

**How to use:** Create an automation on this binary sensor turning ON. Check
the `anomalies` attribute to see which rooms are anomalous and by how much.

#### D9: Most Expensive Circuits
**Entity:** `sensor.universal_room_automation_most_expensive_circuits`
**Unit:** USD

Cost of the #1 most expensive circuit today. Shows the top 5 circuits by
cumulative energy cost across all configured sources (SPAN auto-discovered +
manually added circuits).

**Attributes:**
- `top_circuits` — Top 5 list: `{name, entity_id, panel, power_w, energy_today_kwh, cost_today}`
  sorted by cost descending
- `circuit_count` — Total circuits being monitored

**How to use:** The top circuit is usually HVAC or pool pump. Track changes over
time — if a circuit that's normally #4 suddenly becomes #1, investigate. The
cost is calculated using the effective TOU import rate (base + delivery +
transmission).

**Note:** This sensor requires circuit monitoring to be configured (Part C).
Without any circuits configured, it shows "unavailable".

#### D10: Energy Optimization Potential
**Entity:** `sensor.universal_room_automation_optimization_potential`
**Unit:** USD/day

Estimated daily savings if all current idle waste were eliminated. Uses the
waste watts from D6 (excluding infrastructure rooms) and the current effective
electricity rate.

**Attributes:**
- `waste_watts_total` — Total watts being wasted right now
- `savings_per_day`, `savings_per_month`
- `top_waste_rooms` — Top 3 rooms by waste watts
- `actionable_suggestion` — Plain text like "Turn off Living Room (drawing 150W
  while vacant)"

**How to use:** Add this to a dashboard card. The `actionable_suggestion`
attribute gives you one specific thing to do right now. The monthly savings
estimate shows the long-term value of fixing waste patterns.

## Quality Review

Tier 2 review (2 independent reviews + live validation).

### Review 2 Findings (Race + Restart)
| # | Severity | Finding | Status |
|---|----------|---------|--------|
| H1 | HIGH | EnergyCostPerOccupiedHourSensor read nonexistent `energy_cost_today` key | Fixed — compute from STATE_ENERGY_TODAY * rate |
| H2 | HIGH | MostExpensiveCircuitSensor missing None guard on _circuits | Fixed — added _discovered check |
| H3 | HIGH | InfrastructureRoomSwitch startup race (1 cycle) | Accepted — transient, self-corrects |
| M1 | MEDIUM | EnergyAnomalyBinarySensor computed anomalies twice | Fixed — 5s cache |
| M2 | MEDIUM | 4 HVAC switches lack deferred restore | Pre-existing, not v4.2.0 |
| M3 | MEDIUM | Sensors show 0/None during startup | Fixed — added `available` property |
| M4 | MEDIUM | Missing extra entity not logged | Fixed — warning log |

## Files Changed
- `aggregation.py` — 5 new L3 sensors (D6-D10)
- `config_flow.py` — Dead field removal, infra type, try-except fixes, circuit/grid config
- `coordinator.py` — Infrastructure room flag
- `switch.py` — InfrastructureRoomSwitch
- `energy_circuits.py` — Configurable circuit sources
- `energy_billing.py` — Grid import/export preference
- `energy.py` — Wire circuit config + grid entities
- `energy_const.py` — New constants
- `const.py` — ROOM_TYPE_INFRASTRUCTURE
- `strings.json` / `translations/en.json` — All labels
- `PLANNING_v4.x_B4_ENERGY_INTEGRATION.md` — Updated with latest design decisions
