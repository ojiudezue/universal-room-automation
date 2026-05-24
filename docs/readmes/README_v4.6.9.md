# v4.6.9 — Dashboard Sensor Sweep

**Released:** 2026-05-24

## What shipped

Five new/enriched URA sensors that close the contract between coordinators and the URA Dashboard PWA v6.0 (https://ura.phalanxmadrone.com).

### New entities

| Entity | State | Purpose |
|---|---|---|
| `sensor.ura_presence_coordinator_next_state` | enum string | Routine-awareness next-state prediction. **Placeholder model** (state="unknown") pending real model in v4.7.x. |
| `sensor.ura_security_coordinator_aggregator` | armed/disarmed/partial/alert | Locks + cameras roll-up + counts. |
| `sensor.ura_energy_coordinator_recent_decisions` | int (24h count) | Last 20 EC decisions (battery, TOU, load shed, HVAC constraint). |
| `sensor.ura_safety_coordinator_recent_events` | int (24h count) | Last 20 hazard detections + severity_breakdown. |

### Enriched entity

`sensor.ura_hvac_coordinator_hvac_pre_cool_likelihood` — extra_state_attributes now expose forecast peak, anchor period, solar intent.

## Review

**Tier 2-DB scale (3 parallel reviewers)** at user request. 17 findings: 1 CRITICAL + 4 HIGH + 1 MEDIUM fixed pre-ship. Full doc: `docs/reviews/code-review/v4.6.9_dashboard_sensor_sweep.md`.

Notable fix: `_attr_state_class = MEASUREMENT` removed from 3 sensors (string-state or volatile-count-derived states should not record HA long-term statistics).

## Tests

248/248 cycle tests pass; full suite no regressions (57 failed + 14 errors all pre-existing baseline).

## Carry-forward

- v4.7.x: real Routine-Awareness model wires into D1 placeholder
- v4.6.10+: forecast_high property on EC; hazard resolution events; 24h-boundary tests
- PWA cycle: update tabs to subscribe to new entity IDs + render published attribute shapes
