# Frontend Dashboard — Tab Requirements

Don’t make it just about reporting but allow taking action where appropriate.

## Overview Tab
- Display a clear **presence summary**: who is currently home vs. away
- Show identified persons with their current status
- Show key house status items - energy, HVAC, security, safety,
- Weather forecast
- Energy prediction - expected solar, expected excess, expected cost
- House mode.

---

## Presence Tab
Provide detailed presence data across multiple detection layers:

- **Persons**: List identified individuals and their location (on property, in house, away)
- **Property & Guest count**: How many people total are on the property vs. inside the house
- **BLE** (Bermuda): What devices/persons BLE is currently tracking and reporting
- **Cameras**: What camera detections are active and reporting
- **Motion activity sensors**: What’s being reported by sensors and in which rooms
- What the fusion of all these? Room transitions too.
- Some music following elements and summary ie which rooms are enabled, what has happened

---

## Rooms Tab
- Will we really Consider incorporating a **2D floor plan** (floor plan asset can be supplied) or a **3D interior relief** (asset also available) — I have both to supply. But 
- Make the tab **actionable**, not just informational — e.g., users should be able to turn on/off lights in a room directly from the room card

---

## Energy Tab
- Reference the **Energy 3 dashboard** as the design inspiration
- Prioritize a **compact, information-dense** representation of the full energy infrastructure:
  - Solar (current output + Solcast forecast)
  - Batteries (state of charge, charge/discharge rate)
  - Grid (import/export)
  - -Generator
- Energy flow
- Viz solar forecast vs actual on overlaid graphs
- Predicted bill, Energy spend, Energy excess or deficit etc.


- **HVAC**: Good instincts but emphasize what each thermostat is doing and how the system is directing them (pre-cool, coast, etc.)
- 

---

## Security Tab
- Group cameras into three sections:
  - **Inside**
  - **Outside**
  - **Entryways**
- Show relevant security items from URA.
- Allow key options like locking, unlocking arming etc.

## Diagnostics
- As discussed in the first plan iteration
- Anomalies, Coordinator health, Key diagnostics
