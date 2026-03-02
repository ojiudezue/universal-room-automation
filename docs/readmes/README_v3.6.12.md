# v3.6.12 — Security Coordinator (C3)

**Date:** 2026-03-02
**Cycle:** C3 — Security Coordinator
**Priority:** 80 (below Safety 100, above Energy/HVAC/Comfort)

---

## Summary

Delivers the Security Coordinator, the second active-control coordinator after Safety. Manages armed states, entry monitoring, lock control, and security camera triggers. Builds on BaseCoordinator/Manager/diagnostics infrastructure from C0-C2 and house state from Presence (C1).

## New File

- `domain_coordinators/security.py` (~580 lines)
  - `SecurityCoordinator(BaseCoordinator)` — main coordinator
  - `ArmedState` enum: DISARMED, ARMED_HOME, ARMED_AWAY, ARMED_VACATION
  - `EntryVerdict` enum: SANCTIONED, NOTIFY, LOG_ONLY, INVESTIGATE, ALERT, ALERT_HIGH
  - `SanctionChecker` — classifies entries against census/guest lists
  - `EntryProcessor` — evaluates door/window events against armed state
  - `CameraRecordDispatcher` — auto-detects camera platform (Frigate/UniFi/Reolink/generic)
  - `SecurityPatternLearner` — learns normal entry patterns (30-day minimum)

## Modified Files

| File | Changes |
|------|---------|
| `const.py` | 10 `CONF_SECURITY_*` constants, version bump |
| `signals.py` | `SIGNAL_SECURITY_EVENT`, `SIGNAL_SECURITY_ENTITIES_UPDATE`, `SecurityEvent` dataclass |
| `__init__.py` | Security coordinator registration + 4 services |
| `config_flow.py` | `coordinator_security` menu + `async_step_coordinator_security()` |
| `sensor.py` | 4 sensors: armed state, last entry, anomaly, compliance |
| `binary_sensor.py` | `SecurityAlertBinarySensor` |
| `strings.json` / `translations/en.json` | Security config flow strings + toggle |
| `manifest.json` | Version bump to 3.6.0.12 |

## User Requirements Addressed

1. **Lock devices manually configured** — entity selectors in config flow, no auto-discovery
2. **Camera recording opt-in** — disabled by default, cameras assumed on continuous recording
3. **Coordinator can be disabled** — `CONF_SECURITY_ENABLED` / toggle switch
4. **Armed state flag** — coupled to alarm panel if configured, independent otherwise; bidirectional sync
5. **Security lights manually configured** — same pattern as safety emergency lights
6. **Auto-follow off by default** — house state → armed state mapping, must be explicitly enabled
7. **Unknown persons → lock all doors** — immediate lockdown on census detection
8. **Periodic lock check** — configurable interval (default 30 min), runs regardless of armed state

## Services

| Service | Parameters |
|---------|-----------|
| `ura.security_arm` | `state: disarmed/armed_home/armed_away/armed_vacation` |
| `ura.security_disarm` | — |
| `ura.authorize_guest` | `person_name, expires_hours` |
| `ura.add_expected_arrival` | `person_id, window_minutes` |

## Sensors

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.ura_security_armed_state` | sensor | Current armed state |
| `sensor.ura_security_last_entry` | sensor | Last entry event verdict |
| `sensor.ura_security_anomaly` | sensor | Anomaly detection status |
| `sensor.ura_security_compliance` | sensor | Lock compliance rate (%) |
| `binary_sensor.ura_security_alert` | binary_sensor | ON during active alert |

## Config Flow Fields

| Field | Type | Default |
|-------|------|---------|
| `security_lock_entities` | entity (lock, multi) | [] |
| `security_garage_entities` | entity (cover/garage, multi) | [] |
| `security_entry_sensors` | entity (binary_sensor, multi) | [] |
| `security_light_entities` | entity (light, multi) | [] |
| `security_camera_entities` | entity (camera, multi) | [] |
| `security_camera_recording` | bool | False |
| `security_camera_record_duration` | int (seconds) | 30 |
| `security_alarm_panel` | entity (alarm_control_panel) | None |
| `security_auto_follow` | bool | False |
| `security_lock_check_interval` | int (minutes) | 30 |

## Tests

590 existing tests pass. No regressions.
