# AUDIT — Integration-Entry Options Reload Classification (D1)

**Cycle:** RELOAD-WATCHDOG-HAZARD
**Purpose:** Fixture for D2's `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` seed.
Per plan rev-2 §D1 this table enumerates every key writable to the URA
integration (parent) `entry.options` by ANY of the six options-flow steps
reachable from `config_flow.py:2598-2615` (`global_sensors`, `energy_sensors`,
`person_tracking`, `default_notifications`, `camera_census`,
`perimeter_alerting`), and classifies each by consumer read-style. Only rows
verdicted `SAFE` or `SAFE-WITH-DISPATCH` are eligible for the v1 allowlist;
`NEEDS-DISCHARGE-WORK` and `UNSAFE` stay on the reload path (safety net).

## Verdict legend

| Verdict | Meaning |
|---|---|
| SAFE | Every consumer re-reads from `entry.data`/`entry.options` each tick. |
| SAFE-WITH-DISPATCH | Consumer caches, discharged by `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` wire-up in D3. |
| NEEDS-DISCHARGE-WORK | Cached consumer with no refresh signal today; PARKED — reload-path. |
| UNSAFE | Structural change requires full reload (platform re-registration, etc.). |

## Step enumeration

- `global_sensors` — `config_flow.py:2688-2737`
- `energy_sensors` — `config_flow.py:2739-2788`
- `person_tracking` — `config_flow.py:2829-2882`
- `camera_census` — `config_flow.py:2884-3026`
- `perimeter_alerting` — `config_flow.py:3028-3164`
- `default_notifications` — `config_flow.py:7569-7624`

Live probe cross-check: dump `integration_entry.options.keys()` from the
running HA instance (via `ha-mcp` / SSH) at build-time. Any live key not
listed below indicates a hidden write site and blocks the build.

## Per-key table

### global_sensors

| Key | Consumer(s) | Read style | Verdict | Notes |
|---|---|---|---|---|
| `CONF_OUTSIDE_TEMP_SENSOR` | broad; entity-id read via `hass.states.get(...)` on tick; entity-registry re-registration on reload | requires-reload | UNSAFE | Structural; stays on reload path. |
| `CONF_OUTSIDE_HUMIDITY_SENSOR` | same as above | requires-reload | UNSAFE | Structural. |
| `CONF_WEATHER_ENTITY` | same as above | requires-reload | UNSAFE | Structural. |
| `CONF_SOLAR_PRODUCTION_SENSOR` | EC / substrate | requires-reload | UNSAFE | Structural. |
| `CONF_ELECTRICITY_RATE` | EC / cost calc | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked — not in v1 allowlist. |

### energy_sensors

| Key | Consumer(s) | Read style | Verdict | Notes |
|---|---|---|---|---|
| `CONF_WHOLE_HOUSE_POWER_SENSORS` | EC entity registration | requires-reload | UNSAFE | Structural. |
| `CONF_WHOLE_HOUSE_ENERGY_SENSORS` | EC | requires-reload | UNSAFE | Structural. |
| `CONF_HOUSE_DEVICE_POWER_SENSORS` | EC | requires-reload | UNSAFE | Structural. |
| `CONF_HOUSE_DEVICE_ENERGY_SENSORS` | EC | requires-reload | UNSAFE | Structural. |

### person_tracking

| Key | Consumer(s) | Read style | Verdict | Notes |
|---|---|---|---|---|
| `CONF_TRACKED_PERSONS` | PresenceCoordinator subscription set | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_PERSON_DATA_RETENTION` | DB pruner | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_TRANSITION_DETECTION_WINDOW` | transition detector | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |

### default_notifications

| Key | Consumer(s) | Read style | Verdict | Notes |
|---|---|---|---|---|
| `CONF_NOTIFY_SERVICE` | NM | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_NOTIFY_TARGET` | NM | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_NOTIFY_LEVEL` | NM | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |

### camera_census

| Key | Consumer(s) | Read style | Verdict | Notes |
|---|---|---|---|---|
| `CONF_CENSUS_CROSS_VALIDATION` | camera_census fresh read | fresh-read-per-tick | SAFE | Consumer re-reads `entry.options`. (Not admitted to v1 — conservative; add in follow-on w/ cite.) |
| `CONF_CAMERA_PERSON_ENTITIES` | `camera_census.py:1803-1821` fresh (`merged = {**data, **options}` per call); `transit_validator.py:394` cached subs — **discharged by `SIGNAL_URA_TRANSIT_CONFIG_CHANGED`** (subscribe at `:328`, dispatch NEW in D3); `fan_veto.py:353` fresh via caller `_config()` at `actuator_reconciler.py:212-214` (`{**(entry.data or {}), **(entry.options or {})}` per call) | fresh-read + cached-with-signal-refresh | **SAFE-WITH-DISPATCH** | **v1 allowlist member.** |
| `CONF_EGRESS_CAMERAS` | camera_census fresh; transit_validator cached (discharged D3); **`perimeter_alert.py:411, 1622-1623, 3783` CACHED at `async_setup` with NO subscription to `SIGNAL_URA_TRANSIT_CONFIG_CHANGED`** | cached-no-refresh (perimeter_alert) | **NEEDS-DISCHARGE-WORK** | **DROPPED from v1** per HIGH-1; parked follow-up #1. |
| `CONF_PERIMETER_CAMERAS` | camera_census fresh; transit_validator cached (discharged D3); **`perimeter_alert.py:410, 1622-1623, 3783` CACHED, no subscription** | cached-no-refresh | **NEEDS-DISCHARGE-WORK** | **DROPPED from v1** per HIGH-1; parked follow-up #1. |
| `CONF_FACE_RECOGNITION_ENABLED` | face pipeline registration | requires-reload | UNSAFE | Structural. |
| `CONF_ENHANCED_CENSUS` | census engine wiring | requires-reload | UNSAFE | Structural. |
| `CONF_GUEST_VLAN_SSID` | census helper cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_CENSUS_HOLD_INTERIOR` | census hold logic cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_CENSUS_HOLD_EXTERIOR` | census hold logic cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_CENSUS_BLE_CANCEL_ENABLED` | census fresh read | fresh-read-per-tick | SAFE | Not admitted to v1 (conservative). |
| `CONF_CENSUS_DIVERGENCE_DOWNGRADE` | census fusion policy | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_AUTO_ENABLE_PERSON_DETECTION` | D4 scan | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |

### perimeter_alerting

| Key | Consumer(s) | Read style | Verdict | Notes |
|---|---|---|---|---|
| `CONF_PERIMETER_VEHICLE_HOURS_START` | PerimeterAlertManager cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_PERIMETER_VEHICLE_HOURS_END` | PerimeterAlertManager cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_PERIMETER_ENRICHMENT_ENABLED` | enrichment cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_PERIMETER_ENRICHMENT_PROVIDER` | enrichment cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS` | enrichment cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_PERIMETER_ENRICHMENT_MODEL` | enrichment cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_PERIMETER_ENRICHMENT_MAX_TOKENS` | enrichment cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_PERIMETER_ENRICHMENT_PROVIDER_ID` | enrichment cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |
| `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` | perimeter dispatch cached | cached-no-refresh | NEEDS-DISCHARGE-WORK | Parked. |

## `binary_sensor.py:61` — definitive verdict (MED-1)

`grep -n "CONF_CAMERA_PERSON_ENTITIES" custom_components/universal_room_automation/binary_sensor.py`
returns exactly one hit: the `from .const import (...)` block at
`binary_sensor.py:61`. No downstream reference in the module body. The
entity-key literal `"camera_person_detected"` at `:1155` is a distinct
symbol (a diagnostic entity name), not this CONF.

**Verdict: DEAD IMPORT.** Build removes the import in the same PR as a
same-cycle hygiene fix (per plan §D1 AC — "no spot-verify or
deferred-to-build resolution"). No behavioral change.

## v1 allowlist decision

**v1 seed = `{CONF_CAMERA_PERSON_ENTITIES}` only.**

- Other `SAFE` rows (`CONF_CENSUS_CROSS_VALIDATION`,
  `CONF_CENSUS_BLE_CANCEL_ENABLED`) are DEFERRED to a follow-on cycle
  per Marginal-Benefit Decomposition — the observed outage was on the
  camera_person_entities save; admitting more keys buys nothing today
  and expands the surface a reviewer must vet.
- `CONF_EGRESS_CAMERAS` / `CONF_PERIMETER_CAMERAS` are DROPPED per
  HIGH-1 disposition; parked follow-up #1 (wire
  `PerimeterAlertManager` to a re-subscribe signal, then promote).

## Parked follow-ups (mirrors plan §Parked follow-ups)

1. `PerimeterAlertManager` signal wire-up → promote egress + perimeter
   to v2 allowlist. Trigger: operator hits ~5min outage on an
   egress/perimeter-only save.
2. Broader async-reload redesign. Trigger: a genuinely-reload-required
   integration key causes the same outage.
3. Additional `SAFE`/`SAFE-WITH-DISPATCH` keys not admitted to v1.
   Trigger: operator hits reload on a genuinely-safe key.
