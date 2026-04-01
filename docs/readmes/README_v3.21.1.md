# v3.21.1 — Observability (Cycle E)

**Date:** 2026-03-31
**Tests:** 76 new
**Review tier:** Feature (2 adversarial reviews + fixes)

## What Changed

Added observation mode toggles for 3 coordinators and 5 new diagnostic sensors,
giving full transparency into coordinator decision-making without affecting behavior.

### D1: Coordinator Observation Mode Toggles
- `switch.ura_safety_observation_mode` — Safety runs hazard detection but suppresses
  NM alerts, action intents, and safety hazard signals
- `switch.ura_security_observation_mode` — Security evaluates entries but suppresses
  lock commands, NM alerts, and camera triggers
- `switch.ura_presence_observation_mode` — Presence runs inference but suppresses
  house state dispatches and person-arriving signals (including BLE pre-arrival)
- All use RestoreEntity for restart persistence

### D2: HVAC Arrester Status Sensor
- `sensor.ura_hvac_arrester_status` — "monitoring" / "detected" / "grace" / "acting"
- Attributes: overrides_today, overrides_compromised_today, planned_action,
  ac_reset_active, ac_reset_timeout_minutes, per-zone detail

### D3: NM Alert State Sensor
- `sensor.ura_nm_alert_state` — idle / alerting / cooldown / repeating / re_evaluate
- Attributes: active_alert_severity, cooldown_remaining_seconds, messaging_suppressed

### D4: Energy Envoy Status Sensor
- `sensor.ura_energy_envoy_status` — online / offline / stale
- Attributes: offline_count_today, last_reading_age_seconds

### D5: Safety Active Cooldowns Sensor
- `sensor.ura_safety_active_cooldowns` — "none" or "N active"
- Attributes: per-hazard cooldown remaining seconds

### D6: Security Authorized Guests Sensor
- `sensor.ura_security_authorized_guests` — "none" or "N guests"
- Attributes: guest list with expiry, expected arrivals

## Review Findings Fixed
- HIGH: BLE SIGNAL_PERSON_ARRIVING now gated by Presence observation mode
- MEDIUM: SIGNAL_SAFETY_HAZARD dispatch moved inside non-observation block
- MEDIUM: Removed unpopulated arrester attributes (overrides_reverted_today, override_type)

## Files Changed
- `switch.py` — 3 new observation mode switches
- `domain_coordinators/safety.py`, `security.py`, `presence.py` — observation_mode flag + gating
- `person_coordinator.py` — BLE dispatch observation mode check
- `sensor.py` — 5 new diagnostic sensors
