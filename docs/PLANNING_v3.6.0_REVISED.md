# PLANNING v3.6.0 REVISED - Domain Coordinators

**Version:** 3.6.0
**Codename:** "Whole-House Intelligence"
**Status:** In Progress (C0 thru C2 complete, C2.5 next)
**Supersedes:** PLANNING_v3.6.0.md
**Last Updated:** March 1, 2026
**Estimated Effort:** 22-30 hours across 9 cycles (revised: +C0-diag, +diagnostics per cycle)
**Prerequisites:** v3.5.3 deployed (DONE - February 25, 2026)
**Target:** Q2-Q3 2026
**Codebase Baseline:** v3.6.0-c0.3, 21+ Python modules, ~21,500 LOC, 375 tests, 81+ entities/room
**Diagnostics Reference:** COORDINATOR_DIAGNOSTICS_FRAMEWORK_v2.md

---

## 1. OVERVIEW

### What v3.6.0 Delivers

v3.6.0 introduces **domain coordinators** -- whole-house intelligence layers that operate above individual room automation. Each coordinator owns a specific automation domain and actively controls the devices within that domain.

**Current limitation (v3.5.2):** Each room optimizes itself independently. There is no cross-room conflict resolution, no whole-house energy management, no coordinated security response, and HVAC zones compete for resources without arbitration.

**With domain coordinators:** A tiered system of coordinators evaluates triggers in priority order, proposes actions, resolves conflicts through a central manager, and executes approved actions on owned devices. Safety always wins.

### Active Coordinator Philosophy

Coordinators are **active controllers**, not passive advisors. Each coordinator directly executes actions on its owned devices via `hass.services.async_call()`. There is no "propose and wait for human approval" model for routine operations.

However, for **shared devices** (primarily HVAC zones that multiple coordinators may want to influence, and lights that both Security and Comfort might target), a lightweight **ConflictResolver** arbitrates based on coordinator priority, action severity, and confidence scores. Safety actions at CRITICAL severity bypass the queue entirely.

**Override behavior:** Manual user actions are always respected. If a user touches a thermostat (Carrier Infinity sets `preset_mode: manual`), the coordinator backs off until the next house state transition or explicit resume.

### MECE Device Ownership

Every automatable device type is assigned to exactly one coordinator (Mutually Exclusive). All home automation domains are covered (Collectively Exhaustive). No two coordinators independently control the same device. When a coordinator needs another coordinator's device adjusted, it publishes a constraint or request -- it does not make the service call itself.

---

## 2. ARCHITECTURE

### Coordinator Hierarchy

```
COORDINATOR MANAGER (Orchestrator)
│
├── FOUNDATION LAYER (informational, no device control)
│   └── Presence Coordinator (priority 60)
│       Infers house state: AWAY, HOME_DAY, SLEEP, etc.
│       Consumes Census data from v3.5.x
│       Publishes: SIGNAL_HOUSE_STATE_CHANGED
│
├── TIER 1: LIFE SAFETY (priority 100, cannot be overridden)
│   └── Safety Coordinator
│       Smoke, CO, water leak, freeze risk, air quality
│       Owns: water shutoff valve (future), ventilation overrides
│
├── TIER 2: SECURITY (priority 80)
│   └── Security Coordinator
│       Intrusion detection, armed states, entry monitoring
│       Owns: locks, security cameras (recording triggers), alert lights
│
├── TIER 3: INFRASTRUCTURE (priority 40)
│   └── Energy Coordinator
│       TOU optimization, battery, solar, load management
│       Owns: battery storage mode, pool system, EVSEs, generator
│       Governs: HVAC via published constraints
│
├── TIER 4: DOMAIN CONTROL
│   ├── HVAC Coordinator (priority 30)
│   │   Zone-level climate: 3 Carrier Infinity zones
│   │   Owns: climate.* entities, HVAC fans (zone blowers)
│   │   Responds to: Energy constraints, Comfort requests
│   │
│   └── Comfort Coordinator (priority 20)
│       Room-level comfort: fans, portable heaters, lighting
│       Owns: ceiling fans, portable fans, space heaters,
│             dehumidifiers, comfort lighting (brightness/color temp)
│       Signals: HVAC when zone adjustment needed
│
└── SHARED SERVICES (not coordinators)
    ├── Notification Manager
    │   Multi-channel delivery: Pushover, iMessage, WhatsApp, TTS, light patterns
    ├── Conflict Resolver
    │   Priority arbitration for shared device conflicts
    └── Decision Logger / Compliance Tracker
        Diagnostics framework from COORDINATOR_DIAGNOSTICS_FRAMEWORK.md
```

### How Active Coordinators Work

1. **Triggers** (state changes, time patterns, census events) queue **Intents** on the Coordinator Manager.
2. The Manager collects intents in a short batching window (100ms).
3. Coordinators are invoked **in priority order** (Safety first, Comfort last).
4. Each coordinator's `evaluate()` method receives its intents plus shared context (house state, census data) and returns a list of proposed `CoordinatorAction` objects.
5. The **ConflictResolver** groups actions by target device. If multiple coordinators target the same device, the highest effective-priority action wins. Effective priority = `base_priority * severity_factor * confidence_factor`.
6. Approved actions are executed. Each execution is logged by the DecisionLogger. A compliance check is scheduled 2 minutes later to detect overrides.

### Conflict Resolution for Shared Devices

The only devices that can receive conflicting requests are:

| Shared Device | Potential Claimants | Resolution |
|---|---|---|
| HVAC zones (climate.*) | Safety (freeze protect), Energy (coast/setback), HVAC (comfort control) | Safety > Energy > HVAC. Energy publishes constraints; HVAC applies them. Safety overrides directly. |
| Room lights | Security (flash red), Comfort (circadian), Safety (all on) | Safety > Security > Comfort. Winner takes the light for the duration of the action. |

Non-shared devices never conflict because each is owned by exactly one coordinator.

### Relationship to Existing Room Coordinator (coordinator.py)

The existing `UniversalRoomCoordinator` in `coordinator.py` continues to manage per-room state (30s updates), occupancy detection, and local room automation. Domain coordinators operate **above** room coordinators. They do not replace them.

The domain coordinators read room coordinator state (temperatures, occupancy, humidity) as inputs. The room coordinators are unaware of domain coordinators -- they continue functioning as before. Domain coordinator actions (e.g., turning on a ceiling fan via Comfort Coordinator) operate on the same HA entities that room coordinators monitor, but the room coordinator does not attempt to undo domain coordinator actions because:
- Room fans, security lights, and HVAC zones are explicitly excluded from room-level automation once domain coordinators are active.
- A `CONF_DOMAIN_COORDINATORS_ENABLED` toggle gates this behavior.

### Communication Pattern: Event Bus vs Dispatcher

**Decision: Use HA dispatcher signals for coordinator-to-coordinator data sharing. Use the intent queue for trigger-to-coordinator communication.**

Rationale:
- HA's `async_dispatcher_send` / `async_dispatcher_connect` provides synchronous-style delivery within the event loop, which is sufficient for data sharing (house state changes, energy constraints).
- The intent queue provides batching and priority ordering, which is needed for trigger processing.
- A custom event bus (as sketched in the older PLANNING_v3.6.0.md) adds complexity without benefit over HA's built-in dispatcher.

**Signal definitions:**
```python
SIGNAL_HOUSE_STATE_CHANGED = "ura_house_state_changed"
SIGNAL_ENERGY_CONSTRAINT = "ura_energy_constraint"
SIGNAL_COMFORT_REQUEST = "ura_comfort_request"
SIGNAL_CENSUS_UPDATED = "ura_census_updated"
SIGNAL_SAFETY_HAZARD = "ura_safety_hazard"
```

---

## 3. COORDINATOR INVENTORY

| # | Coordinator | Type | Purpose | Owned Devices | Priority | Cycle |
|---|---|---|---|---|---|---|
| 0 | **Base Infrastructure** | Shared | BaseCoordinator, CoordinatorManager, ConflictResolver, Intent/Action models | None | N/A | C0 |
| 1 | **Presence** | Foundation | House state inference (AWAY/HOME/SLEEP/etc.) | None (informational only) | 60 | C1 |
| 2 | **Safety** | Tier 1 | Environmental hazards: smoke, CO, water, freeze, air quality | Water shutoff valve (configurable, auto-close on leak), ventilation override fans | 100 | C2 |
| 3 | **Security** | Tier 2 | Intrusion detection, armed states, entry monitoring | Locks, security camera recording, security alert lights | 80 | C3 |
| 4 | **Notification Manager** | Shared Service | Multi-channel notification delivery | None (uses HA notify services) | N/A | C4 |
| 5 | **Energy** | Tier 3 | TOU optimization, battery, solar, load management, generator | Battery storage mode, pool system (all Pentair circuits + VSF pumps), EVSEs, Generac generator | 40 | C5 |
| 6 | **HVAC** | Tier 4 | Zone-level climate control for 3 Carrier Infinity zones | 3 climate.* zone entities, zone fan modes | 30 | C6 |
| 7 | **Comfort** | Tier 4 | Room-level comfort: fans, portable heaters, lighting adjustments | Ceiling fans (all), portable fans, space heaters, dehumidifiers, comfort lighting (brightness/color temp) | 20 | C7 |

### Clarifications on Previously Ambiguous Items

**Fan Control MECE Resolution:**
The older designs had both HVAC Coordinator and Comfort Coordinator claiming ceiling fans. Resolution:
- **Comfort Coordinator owns all ceiling fans** (speed, direction, on/off). Ceiling fans are room-level comfort devices, not zone-level HVAC infrastructure.
- **HVAC Coordinator owns zone blower fan modes** (the Carrier Infinity `fan_mode` attribute: low/med/high/auto). These are part of the HVAC system itself.
- If HVAC wants a ceiling fan turned on to supplement cooling during energy constraints, it publishes a constraint via `SIGNAL_ENERGY_CONSTRAINT` with `fan_assist: true`, and the Comfort Coordinator honors it.

**Pool Coordinator (does not exist):**
The diagnostics framework mentions a "Pool Coordinator" in examples. There is no standalone Pool Coordinator. Pool equipment (Pentair IntelliCenter: 33 entities, VSF pumps, circuits, heaters, lights) is **fully owned by the Energy Coordinator**. Pool is an energy-managed load, not a comfort system. The Energy Coordinator controls pool pump speed (VSF 20-140 GPM), circuit shedding, and heater scheduling based on TOU rates.

**Lighting Coordinator (does not exist):**
The diagnostics framework mentions a "Lighting Coordinator." There is no standalone Lighting Coordinator. Lighting control is split:
- **Comfort Coordinator:** Room lighting adjustments (brightness, color temperature, circadian rhythm). These are comfort devices.
- **Security Coordinator:** Security-specific light patterns (flash red on intrusion, entry lights on armed entry). These override comfort lighting during security events.
- **Safety Coordinator:** Emergency lighting (all lights 100% for evacuation). This overrides everything.
- **Existing room automation:** Basic occupancy-based on/off remains in room coordinators for rooms where domain coordinators are not yet configured.

**Generator Management:**
The user has a Generac 22kW natural gas generator. This is **owned by the Energy Coordinator**. The Energy Coordinator monitors generator status and, during grid outages, adjusts load shedding priorities to stay within generator capacity. Generator control entities will be discovered during Energy Coordinator implementation. Initial scope: monitoring + load management during outages. Direct generator start/stop control is deferred to a future cycle if entity support exists.

**Notification Manager Role:**
The Notification Manager is a **shared service, not a coordinator**. It does not participate in the intent queue or conflict resolution. It is instantiated by the CoordinatorManager and made available to all coordinators via `self.manager.notification_manager`. It provides `async def notify(message, severity, channels)` and handles routing, quiet hours, deduplication, and channel dispatch. It ships in its own cycle (C4) because Energy Coordinator (C5) is the first coordinator that needs sophisticated notification beyond simple logging.

---

## 4. MECE DEVICE OWNERSHIP TABLE

| Device Type | Device Examples | Owner | Notes |
|---|---|---|---|
| **Smoke/CO detectors** | `binary_sensor.*smoke*`, `sensor.*carbon_monoxide*` | Safety | Read-only monitoring |
| **Water leak sensors** | `binary_sensor.*leak*` | Safety | Read-only monitoring |
| **Water shutoff valve** | `valve.main_water` (future) | Safety | Auto-close on leak |
| **Door/window sensors** | `binary_sensor.front_door`, `binary_sensor.*window*` | Security | Read-only monitoring |
| **Smart locks** | `lock.*` | Security | Auto-lock on arm |
| **Security cameras** | `camera.*` (recording triggers) | Security | Trigger recording |
| **Security alert lights** | Configured subset of lights | Security | Flash patterns during events |
| **Battery storage** | `select.enpower_*_storage_mode`, `number.enpower_*_reserve*`, `switch.enpower_*_grid*`, `switch.enpower_*_charge*` | Energy | Mode, reserve, grid control |
| **Solar monitoring** | `sensor.envoy_*_production*` | Energy | Read-only |
| **Grid monitoring** | `sensor.envoy_*_consumption*`, `sensor.envoy_*_net*` | Energy | Read-only |
| **Pool system** | `switch.madrone_pool_*`, `number.madrone_pool_vsf_*`, `water_heater.madrone_pool_*`, `light.madrone_pool_*` | Energy | All 33 Pentair entities |
| **EV chargers** | `switch.garage_a`, `switch.garage_b`, `sensor.garage_*_power*` | Energy | On/off + monitoring |
| **Generator** | Generac entities (TBD) | Energy | Monitor + load mgmt |
| **Solcast forecast** | `sensor.solcast_*` | Energy | Read-only |
| **HVAC zones** | `climate.thermostat_bryant_wifi_studyb_zone_1`, `climate.up_hallway_zone_2`, `climate.back_hallway_zone_3` | HVAC | Setpoints, presets, modes |
| **HVAC zone fan modes** | `fan_mode` attribute on climate entities | HVAC | Low/med/high/auto |
| **Ceiling fans** | `fan.*_ceiling_fan`, `fan.*_fan` | Comfort | Speed, direction, on/off |
| **Portable fans** | `fan.*_portable*`, `switch.*_fan` (non-ceiling) | Comfort | On/off, speed |
| **Space heaters** | `switch.*_heater`, `climate.*_heater` | Comfort | On/off, temp target |
| **Dehumidifiers** | `humidifier.*`, `switch.*_dehumidifier` | Comfort | On/off, target |
| **Room lights** (comfort) | All `light.*` entities not assigned to Security | Comfort | Brightness, color temp |
| **Temperature sensors** | `sensor.*_temperature` | Read by multiple | Not controlled |
| **Humidity sensors** | `sensor.*_humidity` | Read by multiple | Not controlled |
| **CO2/VOC sensors** | `sensor.*_co2`, `sensor.*_tvoc` | Read by multiple | Not controlled |
| **Occupancy sensors** | `binary_sensor.*_occupancy`, `binary_sensor.*_motion` | Read by multiple | Not controlled |
| **Weather sensors** | `sensor.outdoor_temperature`, `weather.*` | Read by multiple | Not controlled; used by Energy (baselines, battery strategy) and HVAC (pre-conditioning) |
| **Garage cameras** | `camera.garage_*` | Energy | Vehicle detection via LLMVision (read frame on motion) |
| **Person tracking** | Census system (v3.5.x) | Read by multiple | Not controlled |

**Key principle:** Sensors are read by any coordinator that needs them. Only actuators (switches, lights, climate, valves, locks, numbers, selects) have exclusive ownership.

---

## 5. CYCLE BREAKDOWN

Each cycle delivers one coordinator (or one shared infrastructure piece). Cycles are ordered by dependency: later coordinators depend on earlier ones. Simpler coordinators ship first.

A prerequisite bug fix cycle (C-1) ships first to resolve zone device duplication before C0 introduces the Zone Manager parent device.

---

### Cycle -1: Zone Device Duplication Fix
**Version:** v3.5.3
**Scope:** Fix orphaned/duplicate zone devices in the device registry
**Effort:** 1-2 hours
**Dependencies:** None (v3.5.2 baseline)
**Type:** Bug fix (not a coordinator cycle)

**Problem:** Duplicate standalone zone devices appear in the integration device list. Three root causes identified:

1. **Zone rename orphans old device:** When a zone is renamed in the options flow (`async_step_zone_rooms()`), the entry's `CONF_ZONE_NAME` is updated and the entry reloads, creating a new device with identifier `(DOMAIN, f"zone_{new_name}")`. The old device `(DOMAIN, f"zone_{old_name}")` is never removed from the device registry, leaving an empty orphaned device.

2. **Room options allow custom zone names:** The room basic_setup options flow uses `custom_value=True` on the zone selector, letting users type arbitrary zone names that don't correspond to a zone config entry. This can cause zone name strings to exist without zone entries, and subsequent migration may create duplicate entries.

3. **Fragile migration guard:** The `zone_migration_done` flag is stored in `entry.options` (not `entry.data`), so it can be lost during certain option update paths. If migration re-runs, it may create duplicate zone entries for names that already exist.

**Fixes:**

**Fix 1 — Device cleanup on zone rename** (`config_flow.py`):
In `async_step_zone_rooms()`, before updating the zone name, remove the old zone device from the device registry:
```python
old_zone_name = zone_entry.data.get(CONF_ZONE_NAME) or zone_entry.options.get(CONF_ZONE_NAME)
if old_zone_name and old_zone_name != new_zone_name:
    dev_reg = dr.async_get(self.hass)
    old_device = dev_reg.async_get_device(identifiers={(DOMAIN, f"zone_{old_zone_name}")})
    if old_device:
        dev_reg.async_remove_device(old_device.id)
```

**Fix 2 — Disable custom zone names in room options** (`config_flow.py`):
Change `custom_value=True` to `custom_value=False` in `async_step_basic_setup()` room options zone selector. The initial config flow already uses `custom_value=False`. Users who need a new zone should create one via the "Add Zone" flow, not by typing a name in the room options.

**Fix 3 — Harden migration guard** (`__init__.py`):
Move `zone_migration_done` from `entry.options` to `entry.data` so it survives option resets. Additionally, the existing name-based duplicate check in `_migrate_zone_names_to_entries()` is retained as a secondary guard.

**Fix 4 — Device cleanup on zone unload** (`__init__.py`):
In `async_unload_entry()` for zone entries, remove the zone device from the device registry when the zone entry is fully unloaded:
```python
if entry_type == ENTRY_TYPE_ZONE:
    zone_name = entry.data.get(CONF_ZONE_NAME)
    if zone_name:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_device(identifiers={(DOMAIN, f"zone_{zone_name}")})
        if device:
            dev_reg.async_remove_device(device.id)
```

**Fix 5 — Startup orphan cleanup** (`__init__.py`):
On integration entry setup, scan the device registry for zone devices that don't match any current zone config entry and remove them. This cleans up orphans from previous renames or failed migrations:
```python
dev_reg = dr.async_get(hass)
active_zone_names = {
    e.data.get(CONF_ZONE_NAME, "").lower()
    for e in hass.config_entries.async_entries(DOMAIN)
    if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE
}
for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
    for identifier in device.identifiers:
        if identifier[0] == DOMAIN and identifier[1].startswith("zone_"):
            zone_name = identifier[1][5:]  # strip "zone_" prefix
            if zone_name.lower() not in active_zone_names:
                dev_reg.async_remove_device(device.id)
```

**Modified files:**
| File | Change |
|---|---|
| `config_flow.py` | Fix 1 (zone rename cleanup) + Fix 2 (disable custom_value in room zone selector) |
| `__init__.py` | Fix 3 (migration guard in entry.data) + Fix 4 (unload cleanup) + Fix 5 (startup orphan scan) |

**Estimated total lines:** ~60 new/modified

**Verification:**
- [ ] Rename a zone — old device is removed, new device appears, no orphan
- [ ] Delete a zone entry — zone device is removed from device registry
- [ ] Room options zone selector no longer allows typing custom zone names
- [ ] Restart HA after manually creating orphaned zone device — orphan is cleaned up
- [ ] Migration does not re-run if `zone_migration_done` is already set
- [ ] All 324 existing tests still pass
- [ ] Integration device list shows exactly one device per active zone, no duplicates

---

### Cycle 0: Base Infrastructure — COMPLETE
**Version:** v3.6.0-c0 through v3.6.0-c0.3
**Scope:** Shared framework that all coordinators build on
**Effort:** ~6 hours (actual, across 4 sub-releases)
**Dependencies:** v3.5.3 (zone duplication fix)
**Status:** DEPLOYED (Feb 26-28, 2026)

**What shipped:**
- [x] `BaseCoordinator` abstract class with `async_setup()`, `evaluate()`, `async_teardown()`, `_enabled` property
- [x] `CoordinatorManager` with intent queue, priority-ordered processing loop, context building
- [x] `ConflictResolver` with priority * severity * confidence scoring
- [x] `Intent` and `CoordinatorAction` data classes (including `ServiceCallAction`, `NotificationAction`, `ConstraintAction`)
- [x] `HouseState` enum (9 states) and `HouseStateMachine` with valid transitions and hysteresis
- [x] `Severity` enum with `SEVERITY_FACTORS` multipliers
- [x] Dispatcher signal constants (`signals.py`)
- [x] Config flow addition: `CONF_DOMAIN_COORDINATORS_ENABLED` toggle
- [x] Database schema additions: `decision_log`, `compliance_log`, `house_state_log` tables
- [x] Coordinator Manager sensor: `sensor.ura_coordinator_manager`
- [x] House state sensor: `sensor.ura_house_state`
- [x] Coordinator summary sensor: `sensor.ura_coordinator_summary`

**What shipped in sub-releases (c0.1-c0.3):**
- [x] c0.1: Camera census discovery and periodic updates
- [x] c0.2: **Integration page organization** — Zone Manager and Coordinator Manager as separate config entries (not `via_device` hierarchy — see Implementation Note below). Zones migrated to Zone Manager entry. Camera census graceful degradation across 4 platforms (Frigate, UniFi, Reolink, Dahua). Per-camera binary counting. Face recognition from Frigate.
- [x] c0.3: Fix coordinator entities unavailable — entity registry cleanup for unique_id conflicts during CM migration

**Implementation Note — `via_device` removed:**
The original plan (and Section 6) specified `via_device` chains for device hierarchy (zones via Zone Manager, Zone Manager via integration, coordinators via Coordinator Manager). In practice, `via_device` caused **duplicate entries** on the HA integration page: zone devices appeared both under their own config entry AND under the parent's entry. The fix (c0.2) was to create Zone Manager and Coordinator Manager as **separate config entries** instead of devices under the integration entry, and to remove all `via_device` references. Each config entry appears as its own collapsible group on the integration page. This achieves the same organizational goal without duplicates.

**New files:**
| File | Purpose | Actual Lines |
|---|---|---|
| `domain_coordinators/__init__.py` | Package init | 5 |
| `domain_coordinators/base.py` | BaseCoordinator, Intent, CoordinatorAction, Severity | 225 |
| `domain_coordinators/manager.py` | CoordinatorManager, ConflictResolver | 452 |
| `domain_coordinators/house_state.py` | HouseState, HouseStateMachine, transition rules | 200 |
| `domain_coordinators/signals.py` | Signal constants, shared data classes | 60 |

**Modified files:**
| File | Change |
|---|---|
| `__init__.py` | CoordinatorManager init, Zone Manager migration, Coordinator Manager migration, entity registry cleanup, separate config entry handlers |
| `config_flow.py` | `CONF_DOMAIN_COORDINATORS_ENABLED`, zone manager/coordinator manager migration steps, zone setup targets ZM entry |
| `const.py` | New constants: `ENTRY_TYPE_ZONE_MANAGER`, `ENTRY_TYPE_COORDINATOR_MANAGER`, version |
| `database.py` | `decision_log`, `compliance_log`, `house_state_log` table creation |
| `sensor.py` | `CoordinatorManagerSensor`, `HouseStateSensor`, `CoordinatorSummarySensor` (unconditional via CM entry) |
| `binary_sensor.py` | Zone Manager and Coordinator Manager entry type handlers |
| `aggregation.py` | Zone Manager sensor setup, removed `via_device` from zone DeviceInfo |
| `camera_census.py` | Per-platform availability, 4-platform support, face recognition, degraded mode |
| `music_following.py` | Zone player config lookup checks Zone Manager entry first |
| `strings.json` | `zone_added` abort reason |
| `translations/en.json` | `zone_added` abort reason |

**Verification (all passing):**
- [x] `CoordinatorManager` starts and stops cleanly with HA lifecycle
- [x] Intent queue processes and drains correctly
- [x] ConflictResolver selects highest-priority action per device
- [x] HouseStateMachine enforces valid transitions and hysteresis
- [x] `sensor.ura_coordinator_manager` shows status
- [x] `sensor.ura_house_state` shows current state
- [x] `sensor.ura_coordinator_summary` shows aggregate status
- [x] Config toggle enables/disables coordinator system
- [x] Integration page: Zone Manager, Coordinator Manager, rooms as separate groups — no duplicates
- [x] Camera census degrades gracefully when platforms unavailable
- [x] 375 tests passing (51+ new)

---

### Cycle 0-diag: Diagnostics Infrastructure — NEXT
**Version:** v3.6.0-c0.4
**Scope:** Reusable diagnostics module for all coordinators + coordinator enable/disable
**Effort:** 3-4 hours
**Dependencies:** C0 complete
**Reference:** COORDINATOR_DIAGNOSTICS_FRAMEWORK_v2.md

**Rationale:** Every subsequent coordinator cycle needs diagnostics infrastructure
(decision logging, compliance tracking, anomaly detection). Building this once
in a dedicated cycle prevents each coordinator from reinventing it. Also implements
the coordinator enable/disable requirement.

**Anomaly definition (revised from COORDINATOR_DIAGNOSTICS_FRAMEWORK v1):**
An anomaly is defined as: *"given historical data, is there a statistically significant
deviation from normal system behavior?"* This means:
- Anomalies require a historical baseline (minimum sample size before activation)
- Detection uses statistical methods (z-scores, Gaussian posteriors), not hardcoded thresholds
- Sensor disagreements and cross-validation mismatches are NOT anomalies — they are data quality issues
- This definition directly feeds the Bayesian prediction capstone (v4.0) — same inference engine, different timing

**What ships:**
- `domain_coordinators/coordinator_diagnostics.py` — reusable diagnostics module
  - `DecisionLogger` class: logs every coordinator decision to `decision_log` table with scope field
  - `ComplianceTracker` class: checks commanded vs actual state after 2-min delay, detects overrides
  - `AnomalyDetector` base class: statistical deviation from historical baselines
  - `AnomalyRecord` dataclass: timestamp, coordinator_id, anomaly_type, severity ("nominal"/"advisory"/"alert"/"critical"), scope ("house"/"zone:{name}"/"room:{name}"), details, resolution
  - All DB operations through existing `database.py` pattern (`hass.async_add_executor_job`)
- `BaseCoordinator` enhancements:
  - Injected `self.decision_logger`, `self.compliance_tracker`, `self.anomaly_detector`
  - `get_diagnostics_summary()` method returning situation, compliance rate, anomaly count
- Database schema additions:
  - `anomaly_log` table with scope, severity, anomaly_type, details, resolution columns
  - Add `scope` column to `decision_log` and `compliance_log` tables
- Coordinator enable/disable infrastructure (see dedicated section below)
- Cross-cutting diagnostic sensors on Coordinator Manager device:
  - `sensor.ura_system_anomaly` — worst active anomaly across all coordinators
  - `sensor.ura_system_compliance` — aggregate compliance rate
- Consistent sensor state vocabulary:
  - Severity: "nominal", "advisory", "alert", "critical"
  - Learning: "insufficient_data", "learning", "active", "paused"

**New files:**
| File | Purpose | Est. Lines |
|---|---|---|
| `domain_coordinators/coordinator_diagnostics.py` | DecisionLogger, ComplianceTracker, AnomalyDetector, AnomalyRecord | 400 |

**Modified files:**
| File | Change |
|---|---|
| `domain_coordinators/base.py` | Add diagnostics attributes, `get_diagnostics_summary()` |
| `domain_coordinators/manager.py` | Instantiate diagnostics, inject into coordinators, enable/disable methods |
| `database.py` | `anomaly_log` table, `scope` column on existing tables |
| `sensor.py` | Add `sensor.ura_system_anomaly`, `sensor.ura_system_compliance` |
| `config_flow.py` | Per-coordinator enable/disable toggles in CM options flow |
| `const.py` | Diagnostics constants, enable/disable constants |

**Estimated total lines:** ~400 new, ~150 modified

**Verification:**
- [ ] DecisionLogger records decisions with scope field
- [ ] ComplianceTracker detects overrides after 2-min delay
- [ ] AnomalyDetector reports "insufficient_data" with no history
- [ ] Enable/disable toggle works from CM options flow
- [ ] Disabled coordinator: sensors show "disabled", evaluate() skipped, listeners unsubscribed
- [ ] Re-enabled coordinator: async_setup() called, sensors resume
- [ ] `sensor.ura_system_anomaly` shows "nominal" when no anomalies
- [ ] `sensor.ura_system_compliance` shows compliance rate
- [ ] All 375+ tests still pass
- [ ] 15+ new tests

---

### Cycle 1: Presence Coordinator
**Version:** v3.6.0-c1
**Scope:** House state inference from Census + time + activity, zone presence modes
**Effort:** 3-4 hours
**Dependencies:** C0, C0-diag (diagnostics infrastructure)

**What ships:**
- `PresenceCoordinator` -- subscribes to Census updates, entry sensors, geofence. Infers house state via `StateInferenceEngine`. Publishes `SIGNAL_HOUSE_STATE_CHANGED`.
- State inference engine: occupancy-based + time-of-day + activity level
- House state override: `select.ura_house_state_override` (dropdown on CM device, all 9 house states + "auto")
- Config flow: sleep start/end time, geofence entity selection
- **Zone presence modes** with `select` entities for dashboard override (see below)

#### Entity Placement

House state appears on THREE devices — intentional duplication because presence is fundamental:

**Universal Room Automation device (integration entry)** — where all existing house-level room data lives:

| Entity | Type | Purpose |
|---|---|---|
| `sensor.ura_house_state` | sensor | Current house state (duplicated here — most natural place users look) |
| `select.ura_house_state_override` | select | Dashboard dropdown: all 9 states + "auto". Setting to "auto" clears override. |

**Coordinator Manager device (CM entry)** — coordinator infrastructure view:

| Entity | Type | Purpose |
|---|---|---|
| `sensor.ura_cm_house_state` | sensor | Current house state (duplicated — visible alongside coordinator status) |
| `select.ura_cm_house_state_override` | select | Same dropdown, same backing state — either select controls the same override |

**Presence Coordinator device** — full picture of everything Presence knows:

| Entity | Type | Purpose |
|---|---|---|
| `sensor.ura_presence_house_state` | sensor | Current house state (authoritative source — Presence coordinator drives this) |
| `sensor.ura_house_state_confidence` | sensor (diagnostic) | Confidence of inferred state (0.0-1.0) |
| `binary_sensor.ura_house_occupied` | binary_sensor | True when any person detected in house |
| `binary_sensor.ura_house_sleeping` | binary_sensor | True when house state is SLEEP |
| `binary_sensor.ura_guest_mode` | binary_sensor | True when house state is GUEST |
| `sensor.ura_presence_anomaly` | sensor (diagnostic) | Anomaly status: nominal/advisory/alert/critical |
| `sensor.ura_presence_compliance` | sensor (diagnostic) | Compliance rate |

All three `house_state` sensors read the same value from the Presence coordinator. Both `select` entities control the same override — changing one is reflected in the other.

**Each zone device** — zone-scoped presence:

| Entity | Type | Purpose |
|---|---|---|
| `select.ura_{zone}_presence_mode` | select | Dashboard dropdown: `away`/`occupied`/`sleep`/`auto`. "auto" clears override and resumes coordinator-derived mode. |
| `sensor.ura_{zone}_presence_status` | sensor | Current zone mode (away/occupied/sleep/unknown) — shows actual state including when overridden |

#### Zone Presence Modes

Zone-level presence uses a simplified four-state model — not the full 9-state house machine:

| Zone Mode | Meaning | Derived From |
|---|---|---|
| `away` | No occupants detected in this zone | All zone signals quiet past timeout |
| `occupied` | One or more occupants in this zone | Any zone signal active |
| `sleep` | Zone rooms are in sleep state | House state is SLEEP + zone has bedrooms |
| `unknown` | Zone has no sensors to determine presence | No occupancy signals configured for any room in zone |

**House state is NEVER `unknown`** — it always resolves. House state aggregates across all signals (census, all zones, BLE, time of day). If truly nothing is detected, house state is `away`, not unknown. The full 9-state machine always has a valid state.

#### Zone Presence Signal Strategy

Zone mode is derived from three signal tiers, evaluated in priority order. Any single tier firing is sufficient to mark the zone `occupied`:

| Priority | Signal | What It Tells Us | Coverage |
|---|---|---|---|
| 1 | **Room occupancy sensors** (mmWave/PIR) | Definitive presence in specific rooms | Rooms with sensors |
| 2 | **Zone camera person/motion detection** | Presence in shared spaces | Cameras with HA area in zone rooms |
| 3 | **Bermuda BLE person location** | Named person in a zone room | Rooms with BLE scanners |

**How zone cameras work:**
- Census is house-level only (global person count). It is NOT used for zone presence.
- Instead, cameras in zone rooms are used as **room-level occupancy signals** — person/motion detection with a configurable timeout (default 5-10 min), same pattern as PIR/mmWave.
- Camera-to-zone mapping: cameras already have HA area assignments. Rooms map to zones via `CONF_ZONE_ROOMS`. A camera in area "Game Room" that belongs to zone "Upstairs" provides an occupancy signal for that zone.
- Cross-correlation: if higher confidence is needed, correlate across supported camera platforms (Frigate person_count, UniFi/Reolink/Dahua binary detection) — same multi-platform pattern census already uses, just scoped to one camera.
- Typical deployment: one camera in a shared space (game room, living room, family room) anchors zone presence for that zone.

**Zone `away` determination:**
- ALL room occupancy sensors in the zone are clear (past timeout)
- AND all zone cameras show no person/motion (past timeout)
- AND Bermuda BLE has no persons located in zone rooms
- → Zone is `away`

**Zone `unknown` determination:**
- No room occupancy sensors, no cameras, and no BLE scanners in any room of the zone
- → Zone is `unknown` (not falsely reported as `away`)
- Zones with even one sensor in one room will report `away`/`occupied` (not `unknown`)

**Graceful degradation:** Zone presence reliability equals the sensor coverage of its rooms. A zone with mmWave in every room is very accurate. A zone with one PIR in a hallway has gaps but still works. A zone with only a camera in a shared space provides good anchor coverage. A zone with nothing reports `unknown`.

**Rollup logic:** Zone modes aggregate up to house state:
- ANY zone `occupied` → house is HOME (variant based on time of day)
- ALL zones `away` (or `unknown`) → house derives state from census + time (never `unknown`)
- Zone `sleep` follows house SLEEP state (house-scoped, not zone-derived)

**Where modes are exposed:**
- **House mode** on CM device: `sensor.ura_house_state` + `select.ura_house_state_override` (dropdown). Also on Presence device: `sensor.ura_presence_house_state` (same value, authoritative source).
- **Zone mode** on each zone device: `sensor.ura_{zone}_presence_status` (current state) + `select.ura_{zone}_presence_mode` (dropdown override).

**Override hierarchy:**
1. **Coordinator** derives modes automatically from room sensors + zone cameras + BLE + time
2. **House-level override** (`select.ura_house_state_override` set to any state) — overrides house state, propagates to zones (e.g., force AWAY sets all zones to `away`). Set to "auto" to clear.
3. **Zone-level override** (`select.ura_{zone}_presence_mode` set to `away`/`occupied`/`sleep`) — local to that zone, does NOT propagate up (unless it's the last occupied zone going `away`, which triggers house AWAY). Set to "auto" to clear.
4. **Auto-resume** — overrides clear automatically when the coordinator next detects contradicting presence (e.g., force zone `away` reverts to `occupied` when motion fires in that zone)

**What zone modes are NOT:**
- Not a per-zone state machine (no transitions, no hysteresis at zone level)
- Not DAY/EVENING/NIGHT per zone (time variants stay house-scoped)
- Not GUEST/VACATION per zone (those are house-level concepts)

**New files:**
| File | Purpose | Est. Lines |
|---|---|---|
| `domain_coordinators/presence.py` | PresenceCoordinator, StateInferenceEngine, PresenceContext, ZonePresenceTracker | 550 |

**Modified files:**
| File | Change |
|---|---|
| `domain_coordinators/manager.py` | Register Presence in coordinator dict |
| `sensor.py` | Add `ura_presence_house_state`, `ura_house_state_confidence`, per-zone `ura_{zone}_presence_status` |
| `binary_sensor.py` | Add `house_occupied`, `house_sleeping`, `guest_mode` |
| `select.py` | **New platform** — `ura_house_state_override` (on CM), `ura_{zone}_presence_mode` (per zone) |
| `config_flow.py` | Add sleep hours, geofence entity config step |
| `const.py` | Add presence-related constants, zone mode constants |
| `__init__.py` | Register `select` platform |

**Estimated total lines:** ~550 new, ~200 modified

**Diagnostics (uses C0-diag infrastructure):**
| Component | Metric | Source | Learning Frequency |
|---|---|---|---|
| Decision logging | Every house state transition with scope="house", zone mode changes with scope="zone:{name}" | DecisionLogger | N/A |
| Compliance | Census + time agreement with inferred state | ComplianceTracker | N/A |
| Anomaly | Occupancy count deviates from historical norm for this time/day (e.g., normally 2 people at 7 PM Tuesday but census shows 5) | AnomalyDetector | Daily |
| Anomaly | House empty at a time it has never been empty historically | AnomalyDetector | Daily |
| Anomaly | Zone occupied at unusual time (scope="zone:{name}") | AnomalyDetector | Daily |
| Outcome | `PresenceOutcome`: detection_accuracy, false_positive_rate, platform_agreement_rate | OutcomeMeasurement | Daily |

Minimum data before anomaly activation: 14 days of occupancy history.

Additional presence-specific sensors (on Presence device):
- `sensor.ura_presence_anomaly` — anomaly status: nominal/advisory/alert/critical
- `sensor.ura_presence_compliance` — compliance rate

Per-zone entities (on each zone device):
- `select.ura_{zone}_presence_mode` — dropdown: away/occupied/sleep/auto (override control)
- `sensor.ura_{zone}_presence_status` — actual zone state: away/occupied/sleep/unknown

**Verification:**
- [ ] House state transitions correctly: AWAY -> ARRIVING -> HOME_DAY -> HOME_EVENING -> HOME_NIGHT -> SLEEP -> WAKING
- [ ] House state is NEVER `unknown` — always resolves to a valid state
- [ ] Census update with 0 occupants triggers AWAY
- [ ] Census update with occupants + evening time triggers HOME_EVENING
- [ ] Manual override sets state and expires correctly
- [ ] Hysteresis prevents rapid oscillation
- [ ] Zone mode shows `occupied` when room motion/mmWave fires in that zone
- [ ] Zone mode shows `occupied` when zone camera detects person/motion
- [ ] Zone mode shows `occupied` when Bermuda BLE locates person in zone room
- [ ] Zone mode shows `away` when all zone signals are quiet past timeout
- [ ] Zone mode shows `unknown` when zone has no sensors at all
- [ ] Zone mode shows `sleep` when house is in SLEEP state and zone contains bedrooms
- [ ] House-level override to AWAY propagates all zones to `away`
- [ ] Zone-level override auto-resumes when coordinator detects contradicting presence
- [ ] Last occupied zone overridden to `away` triggers house AWAY
- [ ] Zone with only a camera still correctly reports `occupied`/`away`
- [ ] All sensors update in real-time
- [ ] Anomaly sensor shows "insufficient_data" initially (no history yet)
- [ ] Presence can be disabled via CM options without errors
- [ ] 18+ new tests passing

---

### Cycle 2: Safety Coordinator
**Version:** v3.6.0-c2
**Scope:** Environmental hazard detection and response
**Effort:** 3-4 hours
**Dependencies:** C0, C0-diag, C1 (house state for context)

**What ships:**
- `SafetyCoordinator` (priority 100) -- monitors smoke, CO, water leak, freeze risk, air quality, temperature extremes, humidity
- **Full hazard type enumeration** (from long-form design — all 12 types):
  ```python
  class HazardType(StrEnum):
      SMOKE = "smoke"
      FIRE = "fire"
      WATER_LEAK = "water_leak"
      FLOODING = "flooding"           # Multi-sensor or sustained leak — escalated from WATER_LEAK
      CARBON_MONOXIDE = "carbon_monoxide"
      HIGH_CO2 = "high_co2"
      HIGH_TVOC = "high_tvoc"
      FREEZE_RISK = "freeze_risk"
      OVERHEAT = "overheat"           # Excessive heat or rapid temp rise (any season)
      HVAC_FAILURE = "hvac_failure"   # Rapid temp change in wrong direction for season
      HIGH_HUMIDITY = "high_humidity" # Mold risk — tiered thresholds
      LOW_HUMIDITY = "low_humidity"   # Structure damage, health risk
  ```
- **Binary sensor discovery:** auto-discovers `binary_sensor.*smoke*`, `binary_sensor.*leak*`, etc.
- **Numeric sensor monitoring:** CO ppm, CO2 ppm, TVOC, temperature (freeze + overheat), humidity (high + low)
- **Severity classification with full thresholds:**
  - CO: CRITICAL >100ppm, HIGH >50ppm, MEDIUM >35ppm, LOW >10ppm
  - CO2: HIGH >2500ppm, MEDIUM >1500ppm, LOW >1000ppm
  - Freeze: HIGH <35°F, MEDIUM <40°F, LOW <45°F
  - Humidity (normal rooms): HIGH >80%, MEDIUM >70%, LOW >60%
  - Humidity (bathrooms): HIGH >90%, MEDIUM >85%, LOW >80% (see room-type thresholds below)
  - Low humidity: MEDIUM <25%, LOW <30%
- **Rate-of-change detection (bidirectional, date-based season):**
  ```python
  RATE_THRESHOLDS = {
      "temperature_drop": {
          "rate": -5.0,          # °F per 30min
          "hazard": HazardType.HVAC_FAILURE,
          "active_season": "heating",   # Nov-Mar
      },
      "temperature_rise": {
          "rate": 5.0,           # °F per 30min
          "hazard": HazardType.HVAC_FAILURE,
          "active_season": "cooling",   # May-Sep
      },
      "temperature_rise_extreme": {
          "rate": 10.0,          # °F per 30min — possible fire
          "hazard": HazardType.OVERHEAT,
          "active_season": "any",       # Always dangerous
      },
      "humidity_rise": {
          "rate": 20.0,          # % per 30min
          "hazard": HazardType.WATER_LEAK,  # Pipe burst signature
          "active_season": "any",
          "exclude_room_types": ["bathroom"],  # Showers match this pattern
      },
  }
  ```
  Season detection: date-based (heating=Nov-Mar, cooling=May-Sep, shoulder=Apr+Oct → both directions active). No HVAC entity dependency.
- **Room-type-aware humidity thresholds:**
  | Room Type | LOW % | MEDIUM % | HIGH % | Sustained Window |
  |-----------|-------|----------|--------|-----------------|
  | Normal room | 60 | 70 | 80 | 2 hours |
  | Bathroom | 80 | 85 | 90 | 4 hours (post-shower decay) |
  | Basement | 55 | 65 | 75 | 2 hours |
  Room type derived from room config entries. Humidity rate-of-change (spike) detection excludes bathrooms — showers produce the exact same pattern as a pipe burst. Bathrooms only alarm on sustained high (>85% for 4+ hours = ventilation failure, not shower).
- **FLOODING escalation:** If multiple water leak sensors trigger simultaneously, or a single sensor stays "on" for >15 minutes, escalate from WATER_LEAK (HIGH) to FLOODING (CRITICAL). FLOODING triggers water shutoff (if configured) + all emergency responses.
- **Response actions by severity:**
  | Hazard | Severity | Actions |
  |--------|----------|---------|
  | Smoke/Fire | CRITICAL | All lights 100%, notify all channels |
  | CO | CRITICAL | Lights on, ventilation max (fans), notify all |
  | Flooding | CRITICAL | Water shutoff (if configured), lights on, notify all |
  | Water leak | HIGH | Notify, water shutoff (if configured) |
  | Freeze risk | HIGH | Override HVAC to heat (min 55°F), notify |
  | Overheat | HIGH | Override HVAC to cool, notify |
  | High CO2 | MEDIUM | Request ventilation, notify |
  | High TVOC | MEDIUM | Request ventilation, notify |
  | High humidity | MEDIUM | Signal dehumidifier need, notify |
  | HVAC failure | MEDIUM | Notify (diagnostic — can't auto-fix HVAC) |
  | Low humidity | LOW | Log only |
  | Mild humidity/temp drift | LOW | Log only |
- **Light patterns by hazard type** (from long-form design):
  ```python
  LIGHT_PATTERNS = {
      "fire":       {"color": (255, 100, 0), "effect": "flash", "interval_ms": 250},  # Orange flash
      "water_leak": {"color": (0, 0, 255),   "effect": "pulse"},                       # Blue pulse
      "co":         {"color": (255, 100, 0), "effect": "flash", "interval_ms": 500},  # Orange flash (slower)
      "freeze":     {"color": (100, 150, 255), "effect": "pulse"},                     # Light blue pulse
      "warning":    {"color": (255, 255, 0), "effect": "pulse"},                       # Yellow pulse
  }
  ```
- **Water shutoff valve:** Configurable entity (e.g., `valve.main_water`). When configured: auto-close on any water leak or flooding detection. When not configured: alert-only. No hardware exists yet but the code path ships now — plug and play when valve is installed.
- **Alert deduplication** with per-severity suppression windows: CRITICAL=1min, HIGH=5min, MEDIUM=15min, LOW=1hr
- **Test service:** `ura.test_safety_hazard` — triggers a test hazard for notification pipeline verification. Parameters: `hazard_type`, `location`, `severity`. Does NOT trigger real responses (no HVAC override, no valve close), only notifications.
- Sensors: `sensor.ura_safety_status`, `binary_sensor.ura_safety_alert`, `sensor.ura_safety_diagnostics`
- Config flow: water shutoff valve entity (optional), emergency light entity selection, sleep hours config (harmonized with Presence — see C1.1 note)

**New files:**
| File | Purpose | Est. Lines |
|---|---|---|
| `domain_coordinators/safety.py` | SafetyCoordinator, HazardType, Hazard, AlertDeduplicator, RateOfChangeDetector, room-type humidity thresholds | 650 |

**Modified files:**
| File | Change |
|---|---|
| `domain_coordinators/manager.py` | Register Safety in coordinator dict |
| `sensor.py` | Add Safety sensors |
| `binary_sensor.py` | Add safety_alert |
| `config_flow.py` | Add safety config step + sleep hours config (shared with Presence) |
| `const.py` | Add safety constants and thresholds |
| `services.yaml` | Add `ura.test_safety_hazard` service |

**Estimated total lines:** ~650 new, ~120 modified

**Verification:**
- [ ] Smoke sensor "on" triggers CRITICAL response within 5 seconds
- [ ] Water leak triggers HIGH response + valve close (if configured)
- [ ] Water leak with no valve configured triggers HIGH alert only (no error)
- [ ] Sustained water leak (>15min) or multi-sensor leak escalates to FLOODING (CRITICAL)
- [ ] Temperature below 35°F triggers freeze protection (HVAC override to heat)
- [ ] Temperature above safe threshold triggers OVERHEAT (HVAC override to cool)
- [ ] Rapid temp RISE in cooling season (May-Sep) triggers HVAC_FAILURE
- [ ] Rapid temp DROP in heating season (Nov-Mar) triggers HVAC_FAILURE
- [ ] Extreme temp rise (>10°F/30min, any season) triggers OVERHEAT
- [ ] Humidity spike (>20%/30min) in non-bathroom triggers WATER_LEAK early warning
- [ ] Humidity spike in bathroom is IGNORED (shower pattern)
- [ ] Sustained high humidity (>70%, 2hr) in normal room triggers HIGH_HUMIDITY MEDIUM
- [ ] Sustained high humidity in bathroom uses 85% threshold, 4hr window
- [ ] LOW_HUMIDITY (<30%) triggers advisory
- [ ] CO above threshold triggers graded response (10/35/50/100 ppm tiers)
- [ ] CO2 above 1500ppm triggers MEDIUM
- [ ] TVOC above threshold triggers MEDIUM
- [ ] Light patterns differ by hazard type (fire=orange flash, water=blue pulse, etc.)
- [ ] Safety actions always win conflict resolution against any other coordinator
- [ ] Alert deduplication prevents repeat spam with per-severity windows
- [ ] Test service `ura.test_safety_hazard` fires test notification without triggering real responses
- [ ] Sensors show active hazard count and status
- [ ] Safety can be disabled via CM options (though not recommended)
- [ ] 25+ new tests passing

**Diagnostics (uses C0-diag infrastructure):**
| Component | Metric | Source | Learning Frequency |
|---|---|---|---|
| Decision logging | Every hazard response with scope per room/zone | DecisionLogger | N/A |
| Compliance | Emergency lighting activated, HVAC override applied, valve closed | ComplianceTracker | N/A |
| Anomaly | Sensor trigger frequency deviates from historical norm (e.g., smoke detector triggers more than historical baseline) | AnomalyDetector | Monthly |
| Outcome | `SafetyOutcome`: false_alarm_rate, response_time_seconds, hazard_resolution_time | OutcomeMeasurement | Monthly |

Minimum data before anomaly activation: 30 days (safety events are rare).

Additional safety-specific sensors:
- `sensor.ura_safety_anomaly` — on Safety device
- `sensor.ura_safety_compliance` — on Safety device

---

### Cycle 2.5: Safety Glanceability + Scoped Discovery
**Version:** v3.6.0.3
**Scope:** Scoped sensor discovery with global device config flow, glanceable entities, anomaly fix, push updates
**Effort:** 3-4 hours
**Dependencies:** C2 complete (v3.6.0.2 deployed)
**Full spec:** `docs/MINIPLAN_v3.6.0.3.md`
**Builder Model:** Opus 4.6

**Problem:** The Safety Coordinator device page has 5 entities that don't answer basic questions: how many things are wrong, where, is it water or air, and what scope. The coordinator also vacuums every safety-class entity in HA instead of scoping to what's configured in URA. Anomaly detectors are broken in both Presence and Safety.

**What ships:**

**Scoped sensor discovery:**
- Safety Coordinator stops auto-discovering all safety-class entities in HA
- New two-source model: URA room-configured sensors + global sensors from config flow
- Global sensors mapped back to rooms via HA `area_id` (they may be in a room, just not configured in URA)
- Set-based dedup: sensor in both room config and global config → room location wins
- Config flow extended with 5 EntitySelector fields: smoke/gas, leak, AQ (CO/CO2/TVOC), temperature, humidity

**Anomaly fix:**
- Move `AnomalyDetector` init to top of `async_setup()` in Presence and Safety coordinators
- Show "disabled" (not "not_configured") when coordinator switch is off

**New entities (4):**

| Entity | Type | State | Key question |
|--------|------|-------|-------------|
| `sensor.ura_safety_active_hazards` | sensor | Count (0,1,2...) | How many things are wrong? |
| `binary_sensor.ura_safety_water_leak` | binary_sensor | on/off | Any water problem? |
| `binary_sensor.ura_safety_air_quality` | binary_sensor | on/off | Any air problem? |

**Enriched existing entities:**
- `sensor.ura_safety_status` — add `scope` (clear/room/multi_room/house), `worst_location`, `hazards` list
- `binary_sensor.ura_safety_alert` — add `all_hazards` list (not just worst)

**Infrastructure:**
- Push updates via dispatcher signal (not just polling) for all safety entities
- `EntityCategory.DIAGNOSTIC` on diagnostics/anomaly/compliance sensors
- Guard legacy `_process_alerts()` in aggregation.py when domain coordinators active (prevents independent light flashing)

**Modified files:** safety.py, presence.py, signals.py, config_flow.py, const.py, sensor.py, binary_sensor.py, strings.json, translations/en.json, manifest.json

**Estimated:** ~250 new lines, ~100 modified, 10+ new tests

**Deferred to future cycle:**
- `sensor.ura_safety_affected_rooms` with zone attribution (depends on zone presence fix)
- `sensor.ura_safety_active_responses` (needs response-tracking state management)
- `sensor.ura_safety_recommendations` (needs recommendation engine)

---

### v3.6.0.10 — Adaptive Rate-of-Change Detection
**Version:** v3.6.0.10
**Scope:** Replace fixed rate-of-change thresholds with per-sensor adaptive baselines
**Dependencies:** C2.5 complete (v3.6.0.3 deployed)

**What ships:**
- Replaced fixed rate-of-change thresholds with per-sensor adaptive baselines using MetricBaseline (Welford's algorithm)
- Full 30-min window (no extrapolation), z-score detection (3σ/4σ/5σ severity), generous 2x thresholds during learning
- Rate baselines persist to SQLite, periodic save every 30 min
- Files: `domain_coordinators/safety.py`

---

### Cycle 3: Security Coordinator
**Version:** v3.6.0-c3
**Scope:** Intrusion detection, armed states, entry monitoring
**Effort:** 2-3 hours
**Dependencies:** C0, C0-diag, C1 (house state drives armed state), C2 (Safety can trigger EMERGENCY)

**What ships:**
- `SecurityCoordinator` (priority 80) -- manages armed states (DISARMED/HOME/AWAY/VACATION)
- Armed state auto-follows house state (configurable mapping)
- Entry point monitoring: door/window/garage sensors with sanctioned vs unsanctioned logic
- Census integration: known persons = sanctioned, unknown = investigate/alert
- Geofence integration: approaching person added to expected arrivals
- Anomaly detection: unusual time, unusual entry point, motion without entry
- Response generation: graded from LOG_ONLY to ALERT_HIGH (6 verdict levels: SANCTIONED, NOTIFY, LOG_ONLY, INVESTIGATE, ALERT, ALERT_HIGH)
- Camera recording triggers on HIGH/CRITICAL events
- Security light patterns: intruder (red flash), armed (dim red solid), investigate (yellow pulse)
- **Scheduled entry support:** Recurring visitor schedules (cleaning service, etc.) with `_scheduled_entries: list[ScheduledEntry]` — time-window-based matching for expected recurring visitors
- Services: `ura.security_arm`, `ura.security_disarm`, `ura.authorize_guest`, `ura.add_expected_arrival`
- Sensors: `sensor.ura_security_armed_state`, `binary_sensor.ura_security_alert`, `sensor.ura_security_last_entry`
- Config flow: entry point entity selection, motion sensor selection, camera entity mapping, geofence radius

**New files:**
| File | Purpose | Est. Lines |
|---|---|---|
| `domain_coordinators/security.py` | SecurityCoordinator, ArmedState, EntryProcessor, SanctionChecker, SecurityPatternLearner, SecurityResponseGenerator | 500 |

**Modified files:**
| File | Change |
|---|---|
| `domain_coordinators/manager.py` | Register Security in coordinator dict |
| `sensor.py` | Add Security sensors |
| `binary_sensor.py` | Add security_alert |
| `config_flow.py` | Add security config step |
| `const.py` | Add security constants |

**Estimated total lines:** ~500 new, ~120 modified

**Verification:**
- [ ] Armed state follows house state transitions
- [ ] Door open during AWAY triggers ALERT
- [ ] Known person entry during AWAY triggers SANCTIONED (no alert)
- [ ] Geofence approaching adds expected arrival
- [ ] Camera recording triggers on ALERT/ALERT_HIGH
- [ ] Security lights flash on intrusion
- [ ] Manual arm/disarm services work
- [ ] Guest authorization with expiry works
- [ ] Security can be disabled via CM options without affecting other coordinators
- [ ] 15+ new tests passing

**Diagnostics (uses C0-diag infrastructure):**
| Component | Metric | Source | Learning Frequency |
|---|---|---|---|
| Decision logging | Every armed state transition, alert dispatch, camera trigger | DecisionLogger | N/A |
| Compliance | Locks engaged after arm, cameras recording on alert | ComplianceTracker | N/A |
| Anomaly | Door/window activity deviates from historical pattern (e.g., front door opens at 3 AM when it has never opened 1-5 AM historically) | AnomalyDetector | Monthly |
| Anomaly | Motion in rooms historically inactive at this hour | AnomalyDetector | Monthly |
| Outcome | `SecurityOutcome`: false_alarm_rate, response_time, alert_acknowledgment_rate | OutcomeMeasurement | Monthly |

Minimum data before anomaly activation: 30 days (security baselines are slow to establish).

Additional security-specific sensors:
- `sensor.ura_security_anomaly` — on Security device
- `sensor.ura_security_compliance` — on Security device

---

### Cycle 4: Notification Manager
**Version:** v3.6.0-c4
**Scope:** Multi-channel notification service
**Effort:** 1.5-2 hours
**Dependencies:** C0 (CoordinatorManager provides access)

**What ships:**
- `NotificationManager` shared service -- severity-based routing, channel dispatch
- **Messaging channels (configurable, all optional):**
  - Pushover channel: CRITICAL + HIGH + MEDIUM (existing integration, reliable for urgent alerts)
  - iMessage channel: CRITICAL + HIGH + MEDIUM (via existing notify service)
  - WhatsApp channel: CRITICAL + HIGH + MEDIUM (via WhatsApp integration — newly available)
  - Each channel independently configurable with severity routing. Users can enable any combination.
- Speaker channel (TTS via WiiM media players): CRITICAL + HIGH
- Light pattern channel (visual alerts): all severities via configured alert lights. **8 named patterns** with specific colors/effects: intruder (red flash), armed (dim red solid), fire (orange flash 250ms), water_leak (blue pulse), CO (orange flash 500ms), freeze_risk (light blue pulse), warning (yellow pulse), arriving (warm white fade). **Light state restoration:** captures light states before visual alert, restores them when alert clears.
- **Repeat-until-acknowledged for CRITICAL:** CRITICAL alerts repeat every 30 seconds until acknowledged via `ura.acknowledge_notification` service or dashboard action. This is a life-safety feature — a missed 3 AM smoke alert MUST repeat.
- Quiet hours enforcement (configurable, overridden by CRITICAL)
- Deduplication: identical messages suppressed within configurable windows
- Rate limiting: max notifications per hour per channel
- **Services:** `ura.acknowledge_notification` (stops repeat-until-ack), `ura.test_notification` (test notification delivery on all configured channels)
- **Anomaly-driven notifications** (interface with C0-diag diagnostics):
  - NotificationManager exposes `async def notify_anomaly(anomaly: AnomalyRecord)` method
  - Severity mapping: `advisory` → LOG_ONLY (no notification), `alert` → MEDIUM (messaging channels), `critical` → HIGH (messaging + TTS)
  - Anomaly notifications include: coordinator name, metric, observed vs expected, scope, suggested action
  - Deduplication key includes `(coordinator_id, metric_name, scope)` — same anomaly in the same scope won't re-notify within the suppression window
  - Coordinators call `self.manager.notification_manager.notify_anomaly(anomaly)` after storing the anomaly in DB
  - This is the primary way diagnostics findings reach the user. Without C4, anomalies are logged to DB and visible on dashboard sensors but generate no push notifications.
- Notification history sensor: `sensor.ura_notification_history`
- Config flow: quiet hours, messaging channel selection (Pushover/iMessage/WhatsApp — multi-select), recipient entities per channel, TTS speaker entities, alert light entities, anomaly notification severity threshold (default: `alert`)

**New files:**
| File | Purpose | Est. Lines |
|---|---|---|
| `domain_coordinators/notification_manager.py` | NotificationManager, NotificationRouter, channels, quiet hours, deduplication, repeat-until-ack, light patterns | 450 |

**Modified files:**
| File | Change |
|---|---|
| `domain_coordinators/manager.py` | Instantiate NotificationManager, provide to coordinators |
| `sensor.py` | Add notification history sensor |
| `config_flow.py` | Add notification config step |
| `const.py` | Add notification constants |

**Estimated total lines:** ~450 new, ~100 modified

**Verification:**
- [ ] CRITICAL notification reaches all configured channels, overrides quiet hours
- [ ] CRITICAL notification repeats every 30s until acknowledged
- [ ] `ura.acknowledge_notification` stops repeat cycle
- [ ] `ura.test_notification` sends test message on all configured channels
- [ ] Light patterns use correct colors per hazard type (8 named patterns)
- [ ] Light states restored to pre-alert values after visual alert clears
- [ ] MEDIUM notification goes to configured messaging channels only, respects quiet hours
- [ ] Each messaging channel (Pushover/iMessage/WhatsApp) can be independently enabled/disabled
- [ ] Deduplication suppresses repeat messages within window
- [ ] Rate limiting caps notifications per hour
- [ ] Quiet hours suppress non-critical notifications
- [ ] Anomaly `alert` triggers MEDIUM notification with coordinator + metric details
- [ ] Anomaly `critical` triggers HIGH notification (messaging + TTS)
- [ ] Anomaly `advisory` is logged only, no push notification
- [ ] Anomaly deduplication: same (coordinator, metric, scope) suppressed within window
- [ ] Anomaly notification threshold configurable in options flow
- [ ] History sensor shows recent notifications (including anomaly-driven ones)
- [ ] 10+ new tests passing

---

### Cycle 5: Energy Coordinator
**Version:** v3.6.0-c5
**Scope:** Whole-house energy optimization, battery, solar, pool, EVSEs, generator
**Effort:** 3-4 hours
**Dependencies:** C0, C1 (house state), C4 (notifications)

**What ships:**
- `EnergyCoordinator` (priority 40) -- the largest coordinator
- **TOU awareness:** Three-season PEC rate schedule (summer/winter/shoulder), configurable via options flow. Not hardcoded.
- **Battery strategy:** Self-consumption, savings (TOU arbitrage), or backup mode selection based on TOU period, SOC, solar forecast. Controls `select.enpower_*_storage_mode`, reserve level, grid interaction switches. **Export optimization:** When solar production exceeds home consumption during peak TOU, discharge battery to grid for export credits ($0.16/kWh). Decision tree considers SOC floor, forecast remaining solar hours, and evening demand prediction.
- **Solar forecast integration:** Reads Solcast sensors for day classification (excellent/good/moderate/poor/very_poor). Adjusts battery aggressiveness.
- **Weather integration:** Reads configured weather sensor entities (outdoor temp, humidity, wind, forecast conditions). Used for: (a) battery strategy — pre-charge before storms when solar will drop, (b) HVAC governance — publish weather context in `SIGNAL_ENERGY_CONSTRAINT` so HVAC can pre-cool before extreme heat, (c) energy anomaly detection — consumption normalized against outdoor temperature for accurate baselines. Weather sensors already exist (multiple capable sensors in the home); this is a read-only integration, not a new hardware dependency.
- **Pool optimization:** Tiered approach per ENERGY_COORDINATOR_DESIGN_v2.3:
  - Tier 1: VSF speed reduction (75 GPM -> 30 GPM = 94% power savings during peak)
  - Tier 2: Circuit shedding (infinity edge, booster pump off during peak)
  - Tier 3: Full shutdown (emergency only, <4hr for chemistry)
- **EV charging:** Defer to off-peak. Simple on/off via `switch.garage_a/b`.
- **Vehicle presence detection:** Uses garage cameras + LLMVision integration to determine which vehicles are home. Implementation: (a) configure garage camera entities in options flow, (b) on motion event (person detection or garage door state change), wait 3-5 minutes for scene to settle, (c) call LLMVision to describe what is in frame or count cars. No dedicated vehicle detection model needed — LLM vision describes the scene. Result stored as `sensor.ura_vehicles_home` (count) with attributes listing which bays are occupied. Used by Energy Coordinator for: EV charging decisions (only charge when vehicle is home), departure prediction (vehicle leaves = reduce pre-conditioning), load shedding (no EV to charge = skip that tier).
- **Generator monitoring:** Read Generac status. During outage, adjust load shedding to stay within 22kW capacity.
- **SPAN panel monitoring (read-only):** Reads per-circuit power consumption from SPAN panel entities for anomaly detection. Builds per-circuit consumption baselines by time-of-day and day-of-week. Detects circuit-level anomalies (appliance malfunction, phantom load, unusual usage). **Note:** Circuit-level load shedding via SPAN (turning circuits on/off) is deferred to a future cycle — this cycle is monitoring and anomaly detection only.
- **Livability scoring:** Each energy action has a comfort impact score (0-10) with recovery time estimate and override availability. Energy decisions consider livability — e.g., pool speed reduction (livability 9, barely noticeable) is strongly preferred over HVAC setback (livability 5, occupants feel it). Load shedding order reflects livability ranking.
- **Load shedding priority:** Configurable ordered list. Default: pool speed reduction > EV pause > infinity edge off > pool heater off > HVAC setback > non-essential circuits.
- **HVAC governance:** Publishes `HVACConstraints` via `SIGNAL_ENERGY_CONSTRAINT`:
  - `mode`: normal | pre_cool | coast | shed
  - `setpoint_offset`: -3 to +4 degrees F
  - `occupied_only`: bool
  - `max_runtime_minutes`: int | null
  - `fan_assist`: bool (request Comfort turn on ceiling fans)
- **Decision cycle:** Runs every 5 minutes + on TOU transitions + on significant solar/grid changes.
- Sensors: `sensor.ura_energy_situation`, `sensor.ura_tou_period`, `sensor.ura_battery_strategy`, `binary_sensor.ura_load_shedding_active`, `sensor.ura_energy_savings_today`, `sensor.ura_vehicles_home`
- Config flow: TOU rate schedule, battery priority, controllable load list, reserve SOC target, generator entity mapping, garage camera entities (for vehicle detection), weather sensor entity

**New files:**
| File | Purpose | Est. Lines |
|---|---|---|
| `domain_coordinators/energy.py` | EnergyCoordinator, TOU logic, battery strategy, solar forecast, pool optimization, load shedding, HVAC governance | 700 |

**Modified files:**
| File | Change |
|---|---|
| `domain_coordinators/manager.py` | Register Energy in coordinator dict |
| `sensor.py` | Add Energy sensors |
| `binary_sensor.py` | Add load_shedding_active |
| `config_flow.py` | Add energy config step (TOU rates, battery, loads) |
| `const.py` | Add energy constants |

**Estimated total lines:** ~700 new, ~150 modified

**Verification:**
- [ ] TOU period transitions trigger strategy re-evaluation
- [ ] Battery switches to "savings" mode during peak
- [ ] Pool pump speed reduces to 30 GPM during peak
- [ ] EV charging pauses during peak
- [ ] HVAC constraints published on TOU transitions
- [ ] Load shedding activates when grid import exceeds threshold
- [ ] Solar forecast influences battery charge target
- [ ] Generator monitoring logs outage events
- [ ] Vehicle detection via LLMVision returns car count after garage motion
- [ ] EV charging skips when no vehicle present
- [ ] Weather data feeds into battery strategy (pre-charge before storm)
- [ ] Energy savings sensor tracks daily savings
- [ ] Energy can be disabled; battery reverts to Enphase default behavior
- [ ] 20+ new tests passing

**Diagnostics (uses C0-diag infrastructure):**
| Component | Metric | Source | Learning Frequency |
|---|---|---|---|
| Decision logging | Every battery mode change, load shed, pool speed change with full TOU/SOC/solar context | DecisionLogger | N/A |
| Compliance | Battery actually followed mode command, HVAC respected setback, pool pump at commanded speed | ComplianceTracker | N/A |
| Anomaly | Consumption deviates from historical norm per TOU period + day type + occupancy level (e.g., 40% more than usual for Tuesday peak with 2 people home) | AnomalyDetector | Weekly |
| Anomaly | Solar production deviates from Solcast forecast beyond historical error margin | AnomalyDetector | Weekly |
| Anomaly | Battery SOC trajectory differs from learned charge/discharge pattern | AnomalyDetector | Weekly |
| Anomaly | Per-circuit consumption (SPAN) deviates from historical norm — detects appliance malfunction, phantom loads, or unusual usage patterns at the circuit level | AnomalyDetector | Weekly |
| Outcome | `EnergyOutcome`: import_kwh, export_kwh, savings_vs_baseline, solar_forecast_error_pct, comfort_violations | OutcomeMeasurement | Per TOU period |

Minimum data before anomaly activation: 14 days of energy history.

Additional energy-specific sensors:
- `sensor.ura_energy_anomaly` — on Energy device
- `sensor.ura_energy_compliance` — on Energy device
- `sensor.ura_energy_effectiveness` — daily savings trend

---

### Cycle 6: HVAC Coordinator
**Version:** v3.6.0-c6
**Scope:** Zone-level climate control for 3 Carrier Infinity zones
**Effort:** 2-3 hours
**Dependencies:** C0, C1 (house state), C5 (energy constraints)

**What ships:**
- `HVACCoordinator` (priority 30) -- manages 3 Carrier Infinity zones
- **Zone-to-room mapping:** Configurable via options flow:
  - Zone 1 (climate.thermostat_bryant_wifi_studyb_zone_1): Master Suite rooms
  - Zone 2 (climate.up_hallway_zone_2): Upstairs rooms
  - Zone 3 (climate.back_hallway_zone_3): Main living areas
- **Room condition aggregation:** Reads temperature/humidity/occupancy from all rooms in a zone. Uses **weighted averaging** with configurable per-room weights (primary rooms 1.0, secondary 0.7-0.9) for temperature/humidity. Worst-case used for occupancy (any room occupied = zone occupied).
- **Control strategy model:** Three modes from long-form design:
  - `PRESET_BASED`: Use Carrier presets only (away/home/sleep/wake) — coarse control
  - `TEMPERATURE_BASED`: Direct setpoint control via `hass.services.async_call` — fine control
  - `HYBRID`: Presets for house state transitions, fine-tune setpoints within preset — default mode
- **Energy constraint response:**
  - `normal`: User preferences
  - `pre_cool`: Lower cooling setpoint by offset (e.g., -3F before peak)
  - `pre_heat`: Raise heating setpoint by offset before off-peak ends (winter counterpart of pre_cool)
  - `coast`: Raise cooling setpoint by offset (e.g., +3F during peak)
  - `shed`: Switch to fan_only or off
- **Fan assist relay:** When Energy publishes `fan_assist: true` in HVAC constraints, HVAC forwards a `SIGNAL_COMFORT_REQUEST` to Comfort Coordinator with `fan_assist=True` for all occupied rooms in the constrained zone. This resolves the fan ownership question: HVAC does NOT directly control ceiling fans (Comfort owns those), but HVAC relays the Energy constraint as a comfort request.
- **Preset management:** Uses Carrier presets (away/home/sleep/wake) mapped from house state. Fine-tunes setpoints within presets (HYBRID mode).
- **User override respect:** If `preset_mode == "manual"`, coordinator backs off until next house state transition or explicit resume.
- **Sleep protection:** During SLEEP house state, maximum setpoint offset is configurable (default +/-1.5F).
- **Staggered heat calls:** Priority-based zone activation with configurable max simultaneous zones (default 3) and stagger delay (default 60s).
- **Comfort request handling:** Listens for `SIGNAL_COMFORT_REQUEST` from Comfort Coordinator, adjusts zone if within energy bounds.
- **Weather-aware pre-conditioning:** Reads outdoor temperature from Energy Coordinator's weather context (published via `SIGNAL_ENERGY_CONSTRAINT`). When forecast high exceeds threshold, initiates pre-cool before peak TOU period. When forecast low drops near freeze, initiates pre-heat before off-peak ends.
- Sensors: `sensor.ura_hvac_mode`, `sensor.ura_hvac_zone_{n}_status` (x3)
- Config flow: zone-to-room mapping, max setback, sleep offset limit, stagger settings

**New files:**
| File | Purpose | Est. Lines |
|---|---|---|
| `domain_coordinators/hvac.py` | HVACCoordinator, ZoneManager, room aggregation, energy constraint response, preset mapping, stagger logic | 500 |

**Modified files:**
| File | Change |
|---|---|
| `domain_coordinators/manager.py` | Register HVAC in coordinator dict |
| `sensor.py` | Add HVAC sensors |
| `config_flow.py` | Add HVAC config step (zone mapping, limits) |
| `const.py` | Add HVAC constants |

**Estimated total lines:** ~500 new, ~120 modified

**Verification:**
- [ ] House state AWAY sets all zones to "away" preset
- [ ] House state SLEEP sets all zones to "sleep" preset with limited offset
- [ ] Energy "coast" constraint raises cooling setpoint by offset
- [ ] Energy "pre_cool" constraint lowers cooling setpoint by offset
- [ ] User manual override is detected and respected
- [ ] Zone with higher occupancy gets priority in staggered calls
- [ ] Comfort request honored when within energy bounds
- [ ] Comfort request denied when energy constraint active
- [ ] Pre-cool triggers before peak when forecast high exceeds threshold
- [ ] HVAC can be disabled via CM options
- [ ] 15+ new tests passing

**Diagnostics (uses C0-diag infrastructure):**
| Component | Metric | Source | Learning Frequency |
|---|---|---|---|
| Decision logging | Every stagger decision, preset change, energy constraint response | DecisionLogger | N/A |
| Compliance | Zones respected stagger delays, presets applied correctly | ComplianceTracker | N/A |
| Anomaly | Zone call frequency deviates from historical norm (e.g., zone calling 3x more than normal — possible insulation issue) | AnomalyDetector | Weekly |
| Anomaly | Short cycling rate above historical baseline | AnomalyDetector | Weekly |
| Outcome | `HVACOutcome`: simultaneous_call_reduction_pct, zone_satisfaction_rate, cycle_efficiency | OutcomeMeasurement | Daily |

Minimum data before anomaly activation: 14 days.

Additional HVAC-specific sensors:
- `sensor.ura_hvac_anomaly` — on HVAC device
- `sensor.ura_hvac_compliance` — on HVAC device

---

### Cycle 7: Comfort Coordinator
**Version:** v3.6.0-c7
**Scope:** Room-level comfort: fans, heating, lighting
**Effort:** 2-3 hours
**Dependencies:** C0, C1 (house state), C5 (energy constraints), C6 (HVAC for zone requests)

**What ships:**
- `ComfortCoordinator` (priority 20) -- operates at individual room granularity
- **Person preferences:** Configurable per person via options flow:
  - Temperature preference (cool/heat setpoints)
  - Sensitivity (sensitive/normal/tolerant)
  - Circadian lighting preference
  - Fan preference (on/off, speed)
- **Comfort scoring:** Multi-factor score (0-100) per room:
  - Temperature (40% weight), Humidity (25%), Air quality (25%), Lighting (10%)
  - Weights configurable via options flow
- **Ceiling fan control:** Auto-on when room temp exceeds person's cool preference by threshold. Speed proportional to delta. Auto-off when cooling complete or room vacant.
- **Portable heater control:** Auto-on when room temp below person's heat preference by threshold. Off when target reached or vacant.
- **Dehumidifier control:** Auto-on when room humidity exceeds person's max humidity preference. Off when humidity drops below (max - 10%) hysteresis band or room vacant. Configurable entity mapping for `humidifier.*` and `switch.*_dehumidifier` devices.
- **Circadian lighting:** Adjust color temperature based on time of day for configured lights. Warm (2700K) at night, cool (4500K) midday.
- **HVAC signaling:** When room-level devices cannot achieve comfort target, publish `SIGNAL_COMFORT_REQUEST` to HVAC Coordinator. **HVAC denial handling:** When HVAC responds with DENIED_ENERGY or DENIED_ZONE, Comfort maximizes available room-level devices (fans to max speed, portable heater/cooler on). When HVAC responds with PARTIAL, Comfort logs the gap and adjusts expectations.
- **Energy awareness:** During energy-constrained periods, reduce comfort device usage. Honor `fan_assist` flag from HVAC (relayed from Energy) to run ceiling fans to reduce HVAC load.
- **Bottleneck identification:** `sensor.ura_comfort_bottleneck` shows worst-performing room and limiting factor.
- **Whole-house score:** `sensor.ura_comfort_score` shows weighted average across occupied rooms.
- Sensors: `sensor.ura_comfort_score`, `sensor.ura_comfort_bottleneck`, per-room comfort scores (as attributes)
- Config flow: person preferences, comfort weights, ceiling fan entity mapping, circadian light selection

**New files:**
| File | Purpose | Est. Lines |
|---|---|---|
| `domain_coordinators/comfort.py` | ComfortCoordinator, PersonPreferences, ComfortScoring, CeilingFanController, CircadianLighting, ComfortRequest publisher | 500 |

**Modified files:**
| File | Change |
|---|---|
| `domain_coordinators/manager.py` | Register Comfort in coordinator dict |
| `sensor.py` | Add Comfort sensors |
| `config_flow.py` | Add comfort config step (preferences, fans, lights) |
| `const.py` | Add comfort constants |

**Estimated total lines:** ~500 new, ~120 modified

**Verification:**
- [ ] Room above comfort threshold triggers ceiling fan
- [ ] Fan speed scales with temperature delta
- [ ] Fan off when room vacated or temp satisfied
- [ ] Person preference applied when person in room (via Census)
- [ ] Multi-person room uses compromise preference
- [ ] Circadian lighting adjusts color temp by time of day
- [ ] HVAC request published when local devices insufficient
- [ ] Energy constraint reduces comfort device usage
- [ ] Bottleneck sensor shows correct worst room
- [ ] Comfort can be disabled via CM options
- [ ] 15+ new tests passing

**Diagnostics (uses C0-diag infrastructure):**
| Component | Metric | Source | Learning Frequency |
|---|---|---|---|
| Decision logging | Every comfort evaluation, fan activation, circadian adjustment | DecisionLogger | N/A |
| Compliance | HVAC setpoints match comfort targets, fans at commanded speeds | ComplianceTracker | N/A |
| Anomaly | Comfort scores deviate from seasonal historical norms (e.g., 5 points below normal for February evenings) | AnomalyDetector | Weekly |
| Anomaly | Specific room comfort persistently below historical average (drift detection) | AnomalyDetector | Weekly |
| Outcome | `ComfortOutcome`: average_score, violation_count, bottleneck_duration_minutes | OutcomeMeasurement | Daily |

Minimum data before anomaly activation: 14 days.

Additional comfort-specific sensors:
- `sensor.ura_comfort_anomaly` — on Comfort device
- `sensor.ura_comfort_compliance` — on Comfort device

---

### Cycle Summary

| Cycle | Version | Coordinator | New Lines | Modified Lines | New Tests | Hours | Status |
|---|---|---|---|---|---|---|---|
| C0 | v3.6.0-c0 thru c0.3 | Base Infrastructure | ~940 | ~600 | 51+ | ~6 | DONE |
| C0-diag | v3.6.0-c0.4 | Diagnostics Infrastructure | ~630 | ~360 | 51 | 3-4 | DONE |
| C1 | v3.6.0-c1 thru c1.1 | Presence + Zone Modes + Geofence | ~780 | ~200 | 65 | 3-4 | DONE |
| C2 | v3.6.0-c2 | Safety (full hazard types, bidirectional rate-of-change, room-type humidity) | ~650 | ~120 | 25+ | 3-4 | NEXT |
| C3 | v3.6.0-c3 | Security + scheduled entries | ~550 | ~130 | 15+ | 2-3 | Planning |
| C4 | v3.6.0-c4 | Notification Manager + repeat-until-ack + light patterns | ~450 | ~100 | 15+ | 2-3 | Planning |
| C5 | v3.6.0-c5 | Energy + export optimization + livability scoring | ~750 | ~150 | 20+ | 3-4 | Planning |
| C6 | v3.6.0-c6 | HVAC + room weights + control strategy + fan-assist relay | ~550 | ~130 | 15+ | 2-3 | Planning |
| C7 | v3.6.0-c7 | Comfort + dehumidifier + HVAC denial handling | ~550 | ~130 | 15+ | 2-3 | Planning |
| **Total** | | | **~5,420** | **~1,680** | **198+** | **24-32** | |

Current test count: 491 (C0 + C0-diag + C1 complete)
Post-v3.6.0 target test count: 491 + 130 = **621+ tests**

---

## 6. UI PLAN

### Device Hierarchy — Separate Config Entries (Revised in C0.2)

**IMPORTANT: `via_device` approach abandoned.** The original plan used `via_device` chains
to create parent-child device hierarchy. In practice, this caused **duplicate entries** on
the HA integration page: zone devices appeared both under their own config entry AND under
the parent's entry. The C0.2 fix was to create Zone Manager and Coordinator Manager as
**separate config entries** (not devices under the integration entry) and remove all
`via_device` references.

**Integration page layout after v3.6.0:**

```
Universal Room Automation (integration page — collapsible groups)
│
├── [Universal Room Automation]            ← Integration config entry group
│   └── Universal Room Automation          ← Whole House device (census, transit, perimeter entities)
│       model: "Whole House"
│       identifiers: (DOMAIN, "integration")
│
├── [Zone Manager]                         ← Separate config entry group (ENTRY_TYPE_ZONE_MANAGER)
│   └── URA: Zone Manager                 ← Zone Manager device (zone sensors/entities live here)
│       model: "Zone Manager"
│       identifiers: (DOMAIN, "zone_manager")
│       (Zone sensors created per zone from ZM entry options data)
│
├── [Coordinator Manager]                  ← Separate config entry group (ENTRY_TYPE_COORDINATOR_MANAGER)
│   ├── URA: Coordinator Manager           ← CM device
│   │   entities: sensor.ura_coordinator_manager, sensor.ura_house_state,
│   │             sensor.ura_coordinator_summary, sensor.ura_system_anomaly (C0-diag),
│   │             sensor.ura_system_compliance (C0-diag)
│   │
│   ├── URA: Presence                      ← child coordinator device (C1)
│   │   entities: select.ura_house_state_override, sensor.ura_house_state_confidence,
│   │             binary_sensor.ura_house_occupied, binary_sensor.ura_house_sleeping,
│   │             binary_sensor.ura_guest_mode,
│   │             sensor.ura_presence_anomaly, sensor.ura_presence_compliance (diagnostic)
│   │
│   ├── URA: Safety                        ← (C2)
│   │   entities: sensor.ura_safety_status, binary_sensor.ura_safety_alert,
│   │             sensor.ura_safety_anomaly, sensor.ura_safety_compliance (diagnostic)
│   │
│   ├── URA: Security                      ← (C3)
│   │   entities: select.ura_armed_state, sensor.ura_security_armed_state,
│   │             binary_sensor.ura_security_alert, sensor.ura_security_last_entry,
│   │             sensor.ura_security_anomaly, sensor.ura_security_compliance (diagnostic)
│   │
│   ├── URA: Notifications                 ← (C4)
│   │   entities: sensor.ura_notification_history (diagnostic)
│   │
│   ├── URA: Energy                        ← (C5)
│   │   entities: sensor.ura_energy_situation, sensor.ura_tou_period,
│   │             sensor.ura_battery_strategy, binary_sensor.ura_load_shedding_active,
│   │             sensor.ura_energy_savings_today,
│   │             sensor.ura_energy_anomaly, sensor.ura_energy_compliance,
│   │             sensor.ura_energy_effectiveness (diagnostic)
│   │
│   ├── URA: HVAC                          ← (C6)
│   │   entities: sensor.ura_hvac_mode, sensor.ura_hvac_zone_1_status,
│   │             sensor.ura_hvac_zone_2_status, sensor.ura_hvac_zone_3_status,
│   │             sensor.ura_hvac_anomaly, sensor.ura_hvac_compliance (diagnostic)
│   │
│   └── URA: Comfort                       ← (C7)
│       entities: sensor.ura_comfort_score, sensor.ura_comfort_bottleneck,
│                 sensor.ura_comfort_anomaly, sensor.ura_comfort_compliance (diagnostic)
│
└── (Room config entries — one per room, each its own collapsible group)
    ├── [Kitchen] → Kitchen device (81+ entities)
    ├── [Living Room]
    ├── [Master Bedroom]
    └── ...
```

**DeviceInfo patterns (no `via_device`):**

```python
# Zone Manager device — created under Zone Manager config entry
DeviceInfo(
    identifiers={(DOMAIN, "zone_manager")},
    name="URA: Zone Manager",
    manufacturer="Universal Room Automation",
    model="Zone Manager",
    sw_version=VERSION,
    # NO via_device — lives under its own config entry
)

# Zone sensors — created as entities on Zone Manager device (not separate zone devices)

# Coordinator Manager device — created under Coordinator Manager config entry
DeviceInfo(
    identifiers={(DOMAIN, "coordinator_manager")},
    name="URA: Coordinator Manager",
    manufacturer="Universal Room Automation",
    model="Coordinator Manager",
    sw_version=VERSION,
    # NO via_device — lives under its own config entry
)

# Individual coordinator devices — via_device to CM is safe here because they share
# the same config entry (Coordinator Manager), so no duplicate display issue
DeviceInfo(
    identifiers={(DOMAIN, f"coordinator_{name}")},
    name=f"URA: {name.title()}",
    manufacturer="Universal Room Automation",
    model="Domain Coordinator",
    sw_version=VERSION,
    via_device=(DOMAIN, "coordinator_manager"),  # OK: same config entry
)
```

**Lifecycle rules (revised):**
- Zone Manager and Coordinator Manager are separate config entries created during integration setup migration
- A coordinator device is only created when that coordinator is configured and enabled. Unconfigured coordinators have no device and no entities.
- If a coordinator is **disabled** (not deleted), its device and sensors **remain** in HA but sensors show state "disabled". This allows re-enabling without reconfiguration.
- If a coordinator is **never configured**, no device or entities are created at all.

### Config Flow for Coordinators

The Coordinator Manager device's "Configure" button opens the integration options flow. The first step is a **coordinator selector menu**:

```
┌─────────────────────────────────────┐
│  Configure Domain Coordinators      │
│                                     │
│  Select a coordinator to configure: │
│                                     │
│  ○ Presence Settings                │
│  ○ Safety Monitoring                │
│  ○ Security Settings                │
│  ○ Notification Settings            │
│  ○ Energy Management                │
│  ○ HVAC Zones                       │
│  ○ Comfort Preferences              │
│                                     │
│  [Next]                             │
└─────────────────────────────────────┘
```

Selecting a coordinator opens its specific config sub-flow. This is implemented as an options flow menu step (`async_step_init` returns a menu, each menu item routes to the coordinator's config step).

| Coordinator | Config Step | Key Parameters |
|---|---|---|
| Presence | "Presence Settings" | Sleep start/end time, geofence device tracker entity |
| Safety | "Safety Monitoring" | Water shutoff entity (optional), emergency light entities |
| Security | "Security Settings" | Entry point entities, motion sensors, camera entities, geofence radius |
| Notification | "Notification Settings" | Quiet hours start/end, messaging channels (Pushover/iMessage/WhatsApp — multi-select), per-channel recipients, TTS speaker entities, alert light entities |
| Energy | "Energy Management" | TOU rate schedule (season, periods, rates), battery priority, controllable loads list, reserve SOC, generator entity |
| HVAC | "HVAC Zones" | Zone-to-room mapping (3 zones), max setback, sleep offset, stagger settings |
| Comfort | "Comfort Preferences" | Person preferences (per person: cool/heat setpoints, sensitivity), ceiling fan entity mapping, circadian light entities, comfort weights |

**First-time setup:** When domain coordinators are first enabled (`CONF_DOMAIN_COORDINATORS_ENABLED` toggled on), the config flow guides the user through available coordinators. Each is optional — skip any you don't want. Skipped coordinators are not started and create no device or entities.

**Reconfiguration:** The options flow menu (above) lets you reconfigure any coordinator at any time. You can also enable a previously-skipped coordinator — it will create its device and entities on the next reload.

### Options Flow for Runtime Changes

All coordinator parameters are configurable via Options Flow (Configure button on the Coordinator Manager device or the integration itself). This includes:
- Person preferences (add/remove/edit)
- TOU rate schedules (seasonal changes)
- Zone-to-room mappings (when rooms change)
- Comfort weights
- Load shedding priorities
- Quiet hours
- All entity selections

**Pattern:** Initial setup via config flow sets `entry.data`. All runtime changes via options flow update `entry.options`. Code always merges: `config = {**entry.data, **entry.options}`.

### House State Override (select entity)

Manual house state control is via a `select` entity on the Presence device:

```
select.ura_house_state_override
  options: [AUTO, AWAY, ARRIVING, HOME_DAY, HOME_EVENING, HOME_NIGHT, SLEEP, WAKING, GUEST, VACATION]
  default: AUTO
```

- **AUTO** = Presence Coordinator infers state from Census + time + activity (normal operation)
- Selecting any other value = manual override, bypasses inference
- Override expires at the next house state transition (per Q22) or when user sets back to AUTO
- The `ura.set_house_state` and `ura.clear_house_state_override` services also exist for use in HA automations

The dropdown is immediately visible on the Presence device page and can be added to any Lovelace dashboard.

### Armed State Control (select entity)

Security armed state is via a `select` entity on the Security device:

```
select.ura_armed_state
  options: [AUTO, DISARMED, HOME, AWAY, VACATION]
  default: AUTO
```

- **AUTO** = armed state follows house state via configurable mapping (e.g., AWAY house state → AWAY armed state)
- Manual selection overrides the mapping until next house state transition

### Dashboard / Card Design

**Single Coordinator Summary Card** (recommended approach):

Rather than one card per coordinator (which clutters the dashboard), expose a single `sensor.ura_coordinator_summary` entity on the Coordinator Manager device with state "all_clear" / "advisory" / "alert" / "critical" and attributes containing each coordinator's status.

```yaml
sensor.ura_coordinator_summary:
  state: "all_clear"
  attributes:
    presence: "HOME_EVENING (92%)"
    safety: "normal (0 hazards)"
    security: "home (perimeter monitoring)"
    energy: "normal (off_peak, battery 78%)"
    hvac: "home preset (3 zones active)"
    comfort: "score 84 (bottleneck: game_room temp)"
    notifications_today: 3
    conflicts_resolved_today: 7
```

For users who want deeper visibility:
- Click into any coordinator device to see all its entities
- Each coordinator's diagnostic sensors are marked `entity_category: diagnostic` so they don't clutter default views
- Primary sensors (house_state, energy_situation, comfort_score, etc.) show by default

### Person Preferences Management

Person preferences are stored in `entry.options` under a `person_preferences` key:

```python
# In entry.options
{
    "person_preferences": {
        "oji": {
            "cool_preference": 74.0,
            "heat_preference": 70.0,
            "sensitivity": "normal",
            "circadian": True,
            "fan_preference": "auto"
        },
        "spouse": {
            "cool_preference": 72.0,
            "heat_preference": 71.0,
            "sensitivity": "sensitive",
            "circadian": True,
            "fan_preference": "low"
        }
    }
}
```

The options flow provides an "Add Person" / "Edit Person" sub-flow under Comfort Preferences. Person IDs match Census person IDs from v3.5.x.

---

## 6B. COORDINATOR ENABLE/DISABLE

**Requirement:** Any coordinator can be turned off completely without deleting it.

**Architecture:**
```
Authority:  CoordinatorManager (single source of truth)
Storage:    CM config entry options — CONF_{ID}_ENABLED (default: True for configured coordinators)
Runtime:    BaseCoordinator._enabled property (set by Manager on startup and on config change)
```

**Why Manager is authority (not each coordinator independently):**
- Single config location (CM entry options) instead of scattered per-coordinator config
- Manager can enforce ordering (e.g., don't disable Presence if Security depends on it — warn user)
- Centralized logging of enable/disable events via DecisionLogger
- No synchronization problem — one source of truth

**Lifecycle when disabling:**
1. User toggles coordinator off in Coordinator Manager options flow
2. Manager calls `coordinator.async_teardown()` — unsubscribes all listeners
3. Manager sets `coordinator.enabled = False`
4. On next intent batch, `_async_process_batch` skips disabled coordinators (already implemented in manager.py)
5. Coordinator's sensors report state = "disabled"
6. Decision/compliance/anomaly logging stops for that coordinator
7. Coordinator **remains registered** — device and sensors stay in HA
8. Other coordinators continue operating normally

**Lifecycle when re-enabling:**
1. User toggles coordinator on in options flow
2. Manager calls `coordinator.async_setup()` — re-subscribes listeners
3. Manager sets `coordinator.enabled = True`
4. Sensors resume reporting actual values
5. Logging resumes

**UI:** Per-coordinator toggle in the Coordinator Manager options flow menu:
```
┌─────────────────────────────────────┐
│  Configure Domain Coordinators      │
│                                     │
│  Presence:  [enabled] / disabled    │
│  Safety:    [enabled] / disabled    │
│  Security:  [enabled] / disabled    │
│  Energy:    [enabled] / disabled    │
│  HVAC:      [enabled] / disabled    │
│  Comfort:   [enabled] / disabled    │
│                                     │
│  [Select to configure]              │
│  [Next]                             │
└─────────────────────────────────────┘
```

---

## 7. ANSWERS TO CRITICAL DESIGN QUESTIONS

From DESIGN_QUESTIONS_SUMMARY.md (24 questions). Architecture-affecting questions are answered below. User-preference questions that require Oji's input are marked DEFERRED.

### Architecture-Affecting (Answered)

**Q1: Sleep Detection Method**
**Answer:** Use multi-signal approach: (a) all persons in bedroom areas per Census + (b) time within configured sleep window + (c) low activity for 30+ minutes. No dedicated sleep sensor required. Phone charging status is a future enhancement. Explicit "goodnight" routine via `ura.set_house_state` serves as manual override.

**Q2: Guest Detection Policy**
**Answer:** Moderate. Unknown person detection via Census triggers an advisory notification to the owner. If owner confirms (via service call or HA app), GUEST mode activates. Auto-guest after 15 minutes of continuous unknown presence without owner denial. This avoids false positives from Census glitches while catching real guests.

**Q3: Geofence Integration**
**Answer:** Use HA person entity zones. ARRIVING triggers on first family member entering a configured "near home" zone. Pre-condition house on ARRIVING (lights to welcoming level, HVAC begin comfort recovery). Do not wait for all family members.

**Q7: Camera Integration Depth**
**Answer:** Person detection + auto-recording on security events. No facial recognition in the coordinator itself (Census handles identity via BLE). Cameras trigger recording via `camera.record` service on ALERT/ALERT_HIGH verdicts.

**Q14: Battery Strategy Priority**
**Answer:** Balanced approach with configurable lean. Default: TOU arbitrage (savings mode) during normal operation, backup mode when severe weather alerts active. Reserve level configurable (default 20%). This is a config option, not hardcoded.

**Q22: Override Duration Default**
**Answer:** Until next house state change. This is the most natural behavior: a manual thermostat adjustment during HOME_EVENING persists until the transition to HOME_NIGHT or SLEEP, at which point the coordinator resumes control. Users can also manually clear overrides.

**Q23: Diagnostic Logging Level**
**Answer:** Standard (decisions + errors) by default. Verbose mode available via a diagnostic toggle. All decisions are logged to SQLite regardless of logging level (for the diagnostics framework). HA log output follows the configured level.

**Q24: Conflict Resolution Philosophy**
**Answer:** Safety (1) > Security (2) > Energy (3) > HVAC (4) > Comfort (5). This is the priority order encoded in the ConflictResolver. The ranking reflects: life > property > cost > comfort.

### Answered (Feb 28, 2026)

**Q4: Water Shutoff Valve**
**Answer:** No hardware yet, but ship the code path now as configurable. Safety Coordinator config flow includes an optional `valve.main_water` entity selector. When configured: auto-close on any water leak detection (HIGH severity). When not configured: alert-only, no error. This is plug-and-play — install the valve later, configure the entity, and auto-close activates immediately.

**Q19: Messaging Channels**
**Answer:** Three messaging channels available — Pushover, iMessage, and WhatsApp (newly available integration). All optional, independently configurable with severity routing. Users can enable any combination. Config flow provides multi-select for channel enablement and per-channel recipient configuration.

**Q-new: Vehicle Tracking**
**Answer:** Include in Energy Coordinator (C5). Uses garage cameras + LLMVision integration — no dedicated vehicle detection needed. On garage motion event (person detection or door state change), wait 3-5 min for scene to settle, then call LLMVision to describe the frame / count cars. Result drives EV charging decisions (only charge when vehicle present), departure prediction, and load shedding skip logic. Config flow: garage camera entity selector.

**Q-new: Weather Integration**
**Answer:** Include in Energy Coordinator (C5) — read-only from existing weather sensor entities. Not a prediction difficulty concern; it was deferred because the original plan was cautious about scope. Multiple capable weather sensors already exist in the home. Weather data feeds into: (a) battery strategy — pre-charge before storms, (b) HVAC governance — outdoor temp context in energy constraints, (c) energy anomaly detection — consumption normalized against outdoor temp. HVAC Coordinator (C6) also consumes weather context from Energy's published constraints for pre-cool/pre-heat decisions.

**Q-new: SPAN Panel**
**Answer:** Split approach. **Monitoring for anomaly detection ships in C5 (Energy).** SPAN per-circuit consumption data is read-only, builds per-circuit baselines by time/day, detects circuit-level anomalies (appliance malfunction, phantom loads, unusual usage patterns). **Circuit-level load shedding (turning circuits on/off via SPAN)** is deferred to post-v3.6.0 — requires more hardware testing and careful safety review.

### Remaining Deferred (Require User Input or Future Hardware)

| # | Question | Why Deferred | When Needed |
|---|---|---|---|
| Q5 | Smoke detector integration | Hardware-dependent | C2 (Safety) - auto-discovers available sensors |
| Q6 | Emergency lighting pattern | User preference | C2 (Safety) - configurable, default: all lights 100% |
| Q8 | Smart lock integration | Hardware-dependent | C3 (Security) - auto-discovers lock entities |
| Q9 | Geofence radius | User preference | C1 (Presence) - configurable, default: 200m |
| Q10 | Ceiling fan entity pattern | Environment-dependent | C7 (Comfort) - auto-discovers `fan.*` entities |
| Q11 | Room temperature sensor mapping | Environment-dependent | C7 (Comfort) - uses existing URA room config |
| Q12 | Circadian light selection | User preference | C7 (Comfort) - configurable entity list |
| Q13 | TOU rate schedule | Utility-dependent | C5 (Energy) - configurable via options flow |
| Q15 | Controllable loads | Environment-dependent | C5 (Energy) - configurable entity list |
| Q16 | Zone-to-room mapping | Home-specific | C6 (HVAC) - configurable via options flow |
| Q17 | HVAC pre-conditioning timing | User preference | C6 (HVAC) - configurable, default: on geofence trigger |
| Q18 | Temperature setback limits | User preference | C6 (HVAC) - configurable, default: +/-4F |
| Q20 | TTS speaker entities | Environment-dependent | C4 (Notification) - configurable entity list |
| Q21 | Light alert entities | Environment-dependent | C4 (Notification) - configurable entity list |

**Key design decision:** All deferred questions are resolved through configuration, not code changes. The coordinator discovers what is available and the user configures preferences via the options flow. No question blocks implementation.

---

## 8. WHAT DOES NOT SHIP

Explicit exclusions to prevent scope creep:

| Exclusion | Rationale | When/Where |
|---|---|---|
| **Bayesian parameter learning (auto-tuning)** | Requires 30+ days of data per coordinator. Anomaly detection infrastructure and outcome measurement ship in C0-diag + each coordinator cycle; the auto-tuning/learning layer that adjusts coordinator parameters ships in v4.0.0. | v4.0.0 |
| **Pattern analysis (weekly/monthly reports)** | Aggregated pattern reports (override heatmaps, anomaly trends) require data accumulation. Decision logging, compliance tracking, and anomaly detection ship now; pattern reporting ships later. | v4.0.0 |
| **Direct generator start/stop** | Monitor and load-manage only. Direct control requires hardware verification. | Future |
| **AI-powered custom automation** | v3.4.0 scope (Claude API parsing). Ships after v3.6.0. | v3.4.0 |
| **2D visual mapping** | v4.5.0 scope. | v4.5.0 |
| **New per-room entities from coordinators** | Coordinators create house-level and zone-level sensors only. No additional per-room entities beyond the existing 81+. | By design |
| **Custom Lovelace cards** | Use standard HA entities and auto-entities cards. No custom frontend code. | By design |
| **Vacation mode auto-detection** | The HouseStateMachine allows manual VACATION or auto-detection after 2 days AWAY. Full auto-detection (calendar integration, etc.) is deferred. | v4.0.0 |
| **SPAN panel circuit-level shedding** | Energy Coordinator reads SPAN per-circuit data for anomaly detection (ships in C5). **Turning circuits on/off via SPAN** requires hardware testing and safety review. | Post-v3.6.0 |

**Items moved from exclusions to included (Feb 28 update):**
| Item | Now Ships In | Rationale |
|---|---|---|
| Vehicle tracking | C5 (Energy) | LLMVision + garage cameras makes this simple — describe frame, count cars. No dedicated model needed. |
| Weather integration | C5 (Energy) + C6 (HVAC) | Read-only from existing sensors. Critical for accurate energy baselines and HVAC pre-conditioning. |
| Water shutoff | C2 (Safety) | Ships as configurable — code path ready, entity optional. Plug-and-play when hardware installed. |
| SPAN monitoring | C5 (Energy) | Read-only per-circuit baselines for anomaly detection. Control deferred. |

---

## APPENDIX A: FILE STRUCTURE

After all 8 cycles, the new file structure:

```
custom_components/universal_room_automation/
├── __init__.py                    (modified: coordinator manager init)
├── aggregation.py                 (unchanged)
├── automation.py                  (unchanged)
├── binary_sensor.py               (modified: new coordinator binary sensors)
├── button.py                      (unchanged)
├── camera_census.py               (unchanged)
├── config_flow.py                 (modified: coordinator config steps)
├── const.py                       (modified: new constants)
├── coordinator.py                 (unchanged - existing room coordinator)
├── database.py                    (modified: new tables)
├── entity.py                      (unchanged)
├── manifest.json                  (unchanged)
├── music_following.py             (unchanged)
├── number.py                      (unchanged)
├── pattern_learning.py            (unchanged)
├── perimeter_alert.py             (unchanged)
├── person_coordinator.py          (unchanged)
├── select.py                      (unchanged)
├── sensor.py                      (modified: new coordinator sensors)
├── switch.py                      (unchanged)
├── transit_validator.py           (unchanged)
├── transitions.py                 (unchanged)
│
└── domain_coordinators/           (NEW directory — base files shipped in C0)
    ├── __init__.py                (package init)
    ├── base.py                    (BaseCoordinator, Intent, CoordinatorAction, Severity) — C0
    ├── manager.py                 (CoordinatorManager, ConflictResolver) — C0
    ├── house_state.py             (HouseState, HouseStateMachine) — C0
    ├── signals.py                 (Signal constants, shared data classes) — C0
    ├── coordinator_diagnostics.py (DecisionLogger, ComplianceTracker, AnomalyDetector) — C0-diag
    ├── presence.py                (PresenceCoordinator) — C1
    ├── safety.py                  (SafetyCoordinator) — C2
    ├── security.py                (SecurityCoordinator) — C3
    ├── notification_manager.py    (NotificationManager) — C4
    ├── energy.py                  (EnergyCoordinator) — C5
    ├── hvac.py                    (HVACCoordinator) — C6
    └── comfort.py                 (ComfortCoordinator) — C7
```

**New Python modules:** 12
**Modified Python modules:** 6
**Unchanged modules:** 15
**Estimated new LOC:** ~4,165
**Estimated modified LOC:** ~890
**Total post-v3.6.0 LOC:** ~25,700

---

## APPENDIX B: DATABASE SCHEMA ADDITIONS

```sql
-- Added in C0: Decision logging
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    situation_classified TEXT,
    urgency INTEGER,
    confidence REAL,
    context_json TEXT NOT NULL,
    action_json TEXT NOT NULL,
    expected_savings_kwh REAL,
    expected_cost_savings REAL,
    expected_comfort_impact INTEGER,
    constraints_published TEXT,
    devices_commanded TEXT
);

CREATE INDEX IF NOT EXISTS idx_decision_timestamp ON decision_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_decision_coordinator ON decision_log(coordinator_id);

-- Added in C0: Compliance tracking
CREATE TABLE IF NOT EXISTS compliance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    decision_id INTEGER,
    device_type TEXT NOT NULL,
    device_id TEXT NOT NULL,
    commanded_state TEXT NOT NULL,
    actual_state TEXT NOT NULL,
    compliant BOOLEAN NOT NULL,
    deviation_details TEXT,
    override_detected BOOLEAN,
    override_source TEXT,
    override_duration_minutes INTEGER,
    FOREIGN KEY (decision_id) REFERENCES decision_log(id)
);

CREATE INDEX IF NOT EXISTS idx_compliance_decision ON compliance_log(decision_id);
CREATE INDEX IF NOT EXISTS idx_compliance_timestamp ON compliance_log(timestamp);

-- Added in C0: House state history
CREATE TABLE IF NOT EXISTS house_state_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    state TEXT NOT NULL,
    confidence REAL NOT NULL,
    trigger TEXT,
    previous_state TEXT
);

CREATE INDEX IF NOT EXISTS idx_house_state_timestamp ON house_state_log(timestamp);
```

-- Added in C0-diag: Anomaly detection log
CREATE TABLE IF NOT EXISTS anomaly_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    anomaly_type TEXT NOT NULL,
    severity TEXT NOT NULL,            -- nominal, advisory, alert, critical
    scope TEXT NOT NULL,               -- house, zone:{name}, room:{name}
    details_json TEXT NOT NULL,
    resolution TEXT,                   -- auto_resolved, manual_ack, NULL (open)
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp ON anomaly_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_anomaly_coordinator ON anomaly_log(coordinator_id);
CREATE INDEX IF NOT EXISTS idx_anomaly_severity ON anomaly_log(severity);

-- Added in C0-diag: scope column on existing tables
ALTER TABLE decision_log ADD COLUMN scope TEXT DEFAULT 'house';
ALTER TABLE compliance_log ADD COLUMN scope TEXT DEFAULT 'house';
```

Retention: `decision_log` and `compliance_log` pruned at 90 days. `anomaly_log` pruned at 90 days. `house_state_log` retained for 1 year (feeds v4.0.0 pattern learning).

---

## APPENDIX C: NEW ENTITIES SUMMARY

| Cycle | Entity | Type | Category |
|---|---|---|---|
| C0 | `sensor.ura_coordinator_manager` | sensor | diagnostic |
| C0 | `sensor.ura_house_state` | sensor | primary |
| C0 | `sensor.ura_coordinator_summary` | sensor | primary |
| C1 | `sensor.ura_house_state` | sensor (on URA device) | primary — house state, duplicated for natural access |
| C1 | `select.ura_house_state_override` | select (on URA device) | primary — dropdown: 9 states + auto |
| C1 | `sensor.ura_cm_house_state` | sensor (on CM) | primary — house state, duplicated for coordinator view |
| C1 | `select.ura_cm_house_state_override` | select (on CM) | primary — same override, different device |
| C1 | `sensor.ura_presence_house_state` | sensor (on Presence) | primary — authoritative source |
| C1 | `sensor.ura_house_state_confidence` | sensor (on Presence) | diagnostic |
| C1 | `binary_sensor.ura_house_occupied` | binary_sensor (on Presence) | primary |
| C1 | `binary_sensor.ura_house_sleeping` | binary_sensor (on Presence) | primary |
| C1 | `binary_sensor.ura_guest_mode` | binary_sensor (on Presence) | primary |
| C1 | `select.ura_{zone}_presence_mode` | select (per zone) | primary — dropdown: away/occupied/sleep/auto |
| C1 | `sensor.ura_{zone}_presence_status` | sensor (per zone) | primary — actual zone state |
| C2 | `sensor.ura_safety_status` | sensor | primary |
| C2 | `binary_sensor.ura_safety_alert` | binary_sensor | primary |
| C2 | `sensor.ura_safety_diagnostics` | sensor | diagnostic |
| C3 | `select.ura_armed_state` | select | primary |
| C3 | `sensor.ura_security_armed_state` | sensor | primary |
| C3 | `binary_sensor.ura_security_alert` | binary_sensor | primary |
| C3 | `sensor.ura_security_last_entry` | sensor | primary |
| C4 | `sensor.ura_notification_history` | sensor | diagnostic |
| C5 | `sensor.ura_energy_situation` | sensor | primary |
| C5 | `sensor.ura_tou_period` | sensor | primary |
| C5 | `sensor.ura_battery_strategy` | sensor | primary |
| C5 | `binary_sensor.ura_load_shedding_active` | binary_sensor | primary |
| C5 | `sensor.ura_energy_savings_today` | sensor | primary |
| C5 | `sensor.ura_vehicles_home` | sensor | primary |
| C6 | `sensor.ura_hvac_mode` | sensor | primary |
| C6 | `sensor.ura_hvac_zone_1_status` | sensor | diagnostic |
| C6 | `sensor.ura_hvac_zone_2_status` | sensor | diagnostic |
| C6 | `sensor.ura_hvac_zone_3_status` | sensor | diagnostic |
| C7 | `sensor.ura_comfort_score` | sensor | primary |
| C7 | `sensor.ura_comfort_bottleneck` | sensor | primary |

| C0-diag | `sensor.ura_system_anomaly` | sensor | diagnostic |
| C0-diag | `sensor.ura_system_compliance` | sensor | diagnostic |
| C1 | `sensor.ura_presence_anomaly` | sensor | diagnostic |
| C1 | `sensor.ura_presence_compliance` | sensor | diagnostic |
| C2 | `sensor.ura_safety_anomaly` | sensor | diagnostic |
| C2 | `sensor.ura_safety_compliance` | sensor | diagnostic |
| C3 | `sensor.ura_security_anomaly` | sensor | diagnostic |
| C3 | `sensor.ura_security_compliance` | sensor | diagnostic |
| C5 | `sensor.ura_energy_anomaly` | sensor | diagnostic |
| C5 | `sensor.ura_energy_compliance` | sensor | diagnostic |
| C5 | `sensor.ura_energy_effectiveness` | sensor | diagnostic |
| C6 | `sensor.ura_hvac_anomaly` | sensor | diagnostic |
| C6 | `sensor.ura_hvac_compliance` | sensor | diagnostic |
| C7 | `sensor.ura_comfort_anomaly` | sensor | diagnostic |
| C7 | `sensor.ura_comfort_compliance` | sensor | diagnostic |

**Total new entities:** 48+ (33 primary + 15 diagnostic, house-level; plus 2 per-zone: presence select + status sensor)
**Post-v3.6.0 entities per room:** 81+ (unchanged)
**Post-v3.6.0 house-level entities:** 48+ new + existing aggregation sensors

---

**PLANNING v3.6.0 REVISED**
**Status:** In Progress (C0 complete, C0-diag next)
**Supersedes:** PLANNING_v3.6.0.md
**Last Updated:** February 28, 2026
**Next step:** Implement Cycle 0-diag (Diagnostics Infrastructure)
**Estimated completion:** Q2-Q3 2026
**Changes from previous revision (Feb 25):**
- C0 marked COMPLETE (v3.6.0-c0 through c0.3 deployed)
- `via_device` approach abandoned; replaced with separate config entries (Section 6 rewritten)
- C0-diag cycle inserted between C0 and C1 for diagnostics infrastructure
- Diagnostics section added to every coordinator cycle (C1-C7)
- Coordinator enable/disable architecture defined (Section 6B)
- Anomaly definition constrained: statistical deviation from historical baselines only
- Entity summary updated with 15 new diagnostic sensors across all coordinators
- DB schema updated with `anomaly_log` table and `scope` column
- Effort estimate revised: 22-30 hours (up from 18-24)
- Bayesian auto-tuning remains deferred to v4.0; anomaly detection infrastructure ships in v3.6.0
- Reference: COORDINATOR_DIAGNOSTICS_FRAMEWORK_v2.md for detailed diagnostics spec
