# Optimization Coordinator — Implementation Plan

**Status:** Draft
**Target Version:** v4.x (Activity Log: done, Bayesian B1+B2: done)
**Scope:** Multi-phase, 3-5 cycles

## Mental Model

```
┌─────────────────────────────────────────────────────────────────────┐
│                          HOUSE                                      │
│  House State Machine · Energy Budget · Security Posture · Census    │
│                                                                     │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌───────────┐  │
│  │      ZONE 1         │  │      ZONE 2         │  │  ZONE 3   │  │
│  │  HVAC · Vacancy ·   │  │  HVAC · Vacancy ·   │  │  ...      │  │
│  │  Pre-arrival · Duty │  │  Pre-arrival · Duty │  │           │  │
│  │                     │  │                     │  │           │  │
│  │ ┌─────┐ ┌─────┐    │  │ ┌─────┐ ┌─────┐    │  │ ┌─────┐   │  │
│  │ │Room │ │Room │ ...│  │ │Room │ │Room │ ...│  │ │Room │   │  │
│  │ │  A  │ │  B  │    │  │ │  C  │ │  D  │    │  │ │  E  │   │  │
│  │ └─────┘ └─────┘    │  │ └─────┘ └─────┘    │  │ └─────┘   │  │
│  └─────────────────────┘  └─────────────────────┘  └───────────┘  │
│                                                                     │
│  ┌──────────── Unzoned Rooms ─────────────┐                        │
│  │ Garage Hallway · Kitchen · Bathrooms   │                        │
│  └────────────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────┘

Cross-Cutting Domain Coordinators (serve all levels):
  ├── Presence    (room: occupancy → zone: presence state → house: state machine)
  ├── HVAC        (room: fans/covers → zone: setpoints/presets → house: energy constraint)
  ├── Energy      (room: power tracking → zone: n/a → house: load shedding/budget)
  ├── Security    (room: doors/windows → zone: n/a → house: armed state)
  ├── Safety      (room: leak/air → zone: n/a → house: hazard response)
  ├── Notification (room: alerts → zone: n/a → house: digest/routing)
  └── Music       (room: speaker → zone: n/a → house: follow logic)

          ┌──────────────────────────────────────┐
          │      OPTIMIZATION COORDINATOR        │
          │                                      │
          │  Evaluates health, accuracy, and     │
          │  efficiency at EVERY level:           │
          │                                      │
          │  Room Health Score (per room)         │
          │       ↓ aggregates to                │
          │  Zone Health Score (per zone)         │
          │       ↓ aggregates to                │
          │  House Health Score (system-wide)     │
          │                                      │
          │  Three Pillars:                      │
          │  1. Health Monitoring                 │
          │  2. Prediction Validation             │
          │  3. Goal-Driven Optimization          │
          │                                      │
          │  Two Modes:                          │
          │  · Flag: findings for human review   │
          │  · Agentic: autonomous action        │
          └──────────────────────────────────────┘
```

## What Exists Today (by level)

### Room Level — Rich, 30s cycle
Each room coordinator produces 25+ state keys every 30 seconds:
- **Occupancy:** occupied, motion_detected, presence_detected, ble_persons, occupancy_source, timeout_remaining
- **Environment:** temperature, humidity, illuminance, dark
- **Energy:** power_current, energy_today, energy_cost_today, lights_on_count, fans_on_count
- **Predictions:** next_occupancy_time, peak_occupancy_time, occupancy_pct_7d
- **Diagnostics:** comfort_score, energy_efficiency_score, time_since_motion, occupancy_confidence
- **Actions:** last_action_type, last_action_description, last_action_time
- **Health:** stuck sensor tracking (4h threshold), unavailability grace (60s), failsafe (4h max occupancy)

Each room has 50+ entities (binary sensors, sensors, switches, numbers, selects).

### Zone Level — HVAC-focused, 5min cycle
ZoneState tracks per zone:
- **Climate:** preset_mode, hvac_mode/action, target_temp_high/low, current_temperature
- **Room conditions:** list of RoomCondition (per room: temp, humidity, occupied, weight)
- **Zone presence:** 7-state machine (away, present, sleep, waking, occupied, vacant, unknown)
- **Performance:** override_count_today, ac_reset_count_today, runtime_seconds_this_window
- **Intelligence:** vacancy_sweep_done, zone_persons, camera_face_arrivals_today

### House Level — Coordinator-driven
- **State machine:** 9 states with hysteresis (AWAY, HOME_DAY, SLEEP, GUEST, etc.)
- **Census:** identified_persons, unidentified_count, interior/exterior counts
- **Energy:** solar/battery/grid, load shedding mode, TOU period, predicted bill
- **Security:** armed state, open entries, lock sweep status
- **Safety:** active hazards, affected rooms
- **Diagnostics:** coordinator_summary (all_clear/warning/error), decisions_today, conflicts_resolved_today

### Cross-Coordinator Diagnostics (already built)
- **DecisionLogger:** Records every coordinator decision with confidence, urgency, expected savings
- **ComplianceTracker:** Commanded vs actual state tracking per device
- **AnomalyDetector:** Z-score anomaly detection via MetricBaseline (Welford's algorithm)
- **Activity Log (v3.23.0):** Human-readable decision trail with 14 integration points

---

## Room Health Score

The atomic unit. Each room is programmable software — the Optimization Coordinator's primary job is answering: **"Is this room working as intended?"**

### Dimensions

| Dimension | What It Measures | Data Source | Score Range |
|-----------|-----------------|-------------|-------------|
| **Sensor Health** | Are all configured sensors reporting and not stuck? | `_sensor_on_since`, entity states, `unavailable` checks | 0-100 |
| **Occupancy Accuracy** | Does occupancy match reality? No phantom occupancy, no missed detections? | occupancy_source, timeout patterns, failsafe_fired, stuck sensors excluded | 0-100 |
| **Automation Responsiveness** | When occupancy triggers, do actions happen? Lights turn on? Fans activate? | activity_log (action count vs occupancy transitions), last_action_time vs became_occupied_time | 0-100 |
| **Config-Behavior Alignment** | Is configured behavior actually happening? Fan threshold set but fans never activate? Covers configured but never open? | config keys vs activity_log patterns, compliance_log | 0-100 |
| **Comfort** | Is temperature/humidity within configured comfort range when occupied? | temperature vs comfort_temperature_min/max, humidity vs comfort_humidity_max | 0-100 |
| **Energy Efficiency** | Is the room using energy appropriately? Lights on when vacant? Fans running in empty room? | power_current when not occupied, energy_cost_per_occupied_hour | 0-100 |

**Composite Room Health Score** = weighted average of dimensions.

### Examples of Room-Level Findings

| Finding | Dimension | Severity | Data |
|---------|-----------|----------|------|
| "Garage Hallway motion sensor cycling on/off every 60s for 4h — false occupancy" | Occupancy Accuracy | HIGH | motion history: 259 toggles in 4h, presence: off, camera_person: off |
| "Jaya Bedroom temperature sensor unavailable since restart" | Sensor Health | MEDIUM | entity state: unavailable, last_changed: restart time |
| "Study A has fan_control_enabled but fans never activated in 7 days" | Config-Behavior | LOW | config: fan_control_enabled=true, activity_log: 0 fan_on actions for room |
| "Living Room lights stay on 2h after vacancy (exit action: turn_off configured)" | Automation Responsiveness | HIGH | last_exit time vs lights_on_count still >0 |
| "Master Bedroom at 82°F when occupied, comfort_max is 76°F" | Comfort | MEDIUM | temperature: 82, comfort_temperature_max: 76, occupied: true |

---

## Zone Health Score

Aggregates from room health + HVAC-specific metrics.

### Dimensions

| Dimension | What It Measures | Data Source |
|-----------|-----------------|-------------|
| **Room Health Aggregate** | Worst/average room health score in zone | Room Health Scores |
| **Setpoint Compliance** | Are rooms reaching/maintaining zone setpoint? | room_conditions vs target_temp_high/low |
| **Vacancy Management** | Do vacancy sweeps clear correctly? | vacancy_sweep_done, rooms still occupied after sweep |
| **Pre-Arrival Effectiveness** | Does zone reach comfort before person arrives? | pre-arrival trigger time vs arrival time vs zone temp at arrival |
| **Override Frequency** | How often is HVAC overridden? High = bad config. | override_count_today, ac_reset_count_today |
| **Duty Cycle Health** | Is HVAC runtime reasonable? | runtime_seconds_this_window, runtime_exceeded |

### Examples of Zone-Level Findings

| Finding | Dimension | Severity |
|---------|-----------|----------|
| "Zone 1 pre-cooled 2h before peak but reached setpoint in 45min — reduce lead time" | Pre-Arrival | LOW |
| "Zone 2 overridden 5 times today — setpoints may be misconfigured" | Override Frequency | MEDIUM |
| "Zone 1 Master Bedroom consistently 4°F warmer than Study A — south-facing window? Zone average masks it" | Setpoint Compliance | MEDIUM |
| "Zone 3 vacancy sweep ran but Garage Hallway still occupied (false positive) — delayed zone away" | Vacancy Management | HIGH |

---

## House Health Score

System-wide assessment.

### Dimensions

| Dimension | What It Measures | Data Source |
|-----------|-----------------|-------------|
| **Zone Health Aggregate** | Worst/average zone health | Zone Health Scores |
| **State Machine Accuracy** | Do state transitions match reality? | house_state_log vs census vs person locations |
| **Energy Budget** | Is house meeting cost/consumption targets? | energy_cost_today vs target, predicted_bill |
| **Security Posture** | Is security following house state? Armed when away? | armed_state vs house_state correlation |
| **Cross-Coordinator Harmony** | Are coordinators fighting? Conflicting actions? | conflicts_resolved_today, competing service calls |
| **Prediction Accuracy** | Are system predictions accurate? | energy forecast error, HVAC pre-cool outcome, occupancy prediction accuracy |

### Examples of House-Level Findings

| Finding | Dimension | Severity |
|---------|-----------|----------|
| "House stayed HOME for 30min after last person left — garage hallway false occupancy delayed AWAY" | State Machine | HIGH |
| "Energy cost today $2.50 above 7-day average — load shedding didn't activate during peak" | Energy Budget | MEDIUM |
| "Security didn't arm when house went AWAY at 2 PM — security_auto_follow toggle off?" | Security Posture | HIGH |
| "Energy forecast predicted 45 kWh consumption, actual was 62 kWh — 38% error" | Prediction Accuracy | MEDIUM |

---

## Three Pillars (Room-Up)

### Pillar 1: Health Monitoring

**Room level (every 5 minutes):**
For each room, compute 6 dimension scores from the room coordinator's data dict + activity log + config entry. Flag degraded dimensions.

**Zone level (every 5 minutes):**
Aggregate room scores + evaluate zone-specific HVAC metrics. Flag zones where rooms diverge from zone setpoint.

**House level (every 15 minutes):**
Aggregate zone scores + evaluate state machine accuracy + energy budget + security posture.

**Output:** Per-room, per-zone, and house-level health scores + flagged findings.

### Pillar 2: Prediction Validation

**Room level:**
- Predicted next_occupancy_time vs actual occupancy events (from activity_log)
- Pattern learner accuracy (predicted room transitions vs actual)

**Zone level:**
- Pre-arrival effectiveness (triggered vs arrived vs comfort achieved)
- HVAC daily outcomes (zone_satisfaction_pct from HVACOutcome)

**House level:**
- Energy forecast accuracy (DailyEnergyPredictor already has 30-day rolling accuracy)
- House state transition timing accuracy

**Output:** Accuracy metrics per prediction source. Degradation flags when accuracy drops below threshold.

### Pillar 3: Goal-Driven Optimization

**Built-in goals** (always active):
- Energy: Minimize cost within comfort bounds
- Comfort: Maintain rooms within comfort range when occupied
- Security: Maintain appropriate security posture for house state

**User-injectable goals** (via config flow or service call):
- "Keep Study A below 78°F when occupied"
- "Minimize electricity between 2-7 PM"
- "Alert if any room exceeds 85°F"

**Tier 1 (deterministic, always-on):**
Rule engine checks room/zone/house data against goals. Produces recommendations.

**Tier 2 (LLM-assisted, periodic batch):**
Builds structured summary of health scores + activity log + config. Sends to Claude API for deeper reasoning. Returns findings + optional actions.

---

## Architecture

```
                    ┌──────────────────────────────────┐
                    │     Optimization Coordinator     │
                    │     (BaseCoordinator subclass)    │
                    │     priority: 5 (lowest)          │
                    │     cycle: 5min                   │
                    └──────┬───────────────────────────┘
                           │
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
    ┌─────────────┐ ┌───────────┐ ┌───────────┐
    │   Health    │ │ Prediction│ │   Goal    │
    │  Evaluator  │ │ Validator │ │ Optimizer │
    └──────┬──────┘ └─────┬─────┘ └─────┬─────┘
           │              │             │
           ▼              ▼             ▼
    ┌─────────────────────────────────────────┐
    │          Findings Store                  │
    │  (in-memory + DB: optimization_findings) │
    └──────┬──────────────────────────┬───────┘
           │                          │
    ┌──────▼──────┐           ┌──────▼──────┐
    │  Flag Mode  │           │ Agentic Mode│
    │             │           │             │
    │ · Sensors   │           │ · All Flag  │
    │ · HA Events │           │ · Service   │
    │ · Activity  │           │   Calls     │
    │   Log       │           │ · Config    │
    │ · Logbook   │           │   Updates   │
    │             │           │ · NM Alert  │
    └─────────────┘           └─────────────┘

Data Flow (ingestion):
    Room Coordinators ──30s──▶ room.data (25+ state keys)
    Activity Logger ──event──▶ SIGNAL_ACTIVITY_LOGGED
    Zone Manager ────5min───▶ zone.room_conditions
    Coordinator Manager ─────▶ coordinator health/diagnostics
    Database ───────query───▶ activity_log, compliance_log, outcome_log
    Config Entries ──────────▶ per-room config (what SHOULD happen)
```

### How the Optimizer Reads Each Level

**Room level** — For each room config entry:
```python
coordinator = hass.data[DOMAIN].get(entry.entry_id)  # Room coordinator
data = coordinator.data  # 25+ state keys, updated every 30s
config = {**entry.data, **entry.options}  # What the room is configured to do
# Compare data vs config → health score
```

**Zone level** — For each zone in ZoneManager:
```python
zone_manager = hass.data[DOMAIN].get("zone_manager")
for zone_id, zone in zone_manager.zones.items():
    zone.room_conditions  # Per-room temp/humidity/occupied
    zone.zone_presence_state  # 7-state machine
    zone.target_temp_high/low  # What zone should be
    zone.override_count_today  # How often overridden
```

**House level** — From coordinator manager + aggregation:
```python
cm = hass.data[DOMAIN].get("coordinator_manager")
house_state = cm.house_state  # Current state
for coord_id, coord in cm.coordinators.items():
    # Per-coordinator health from diagnostics
```

---

## Consumption Architecture

### Design Principle: Hierarchy Matches the Mental Model

The three levels (room > zone > house) each get their own dedicated health sensor. The Optimization Coordinator device is the detail view. Digests and notifications bring findings to you.

```
Where to look:
  House level  → Coordinator Manager device: sensor.ura_optimizer_house_summary
  Zone level   → Each Zone device: sensor.{zone}_optimization_health (dedicated, per-zone)
  Room level   → Each Room device: sensor.{room}_optimization_health (dedicated, per-room)
  All details  → Optimization Coordinator device: findings, breakdowns, recommendations
  Don't look   → NM brings critical findings + daily/weekly digests to your phone
```

### Existing URA Device Hierarchy

```
Universal Room Automation          (integration-level, top-level device)
├── URA: Coordinator Manager       (house-level orchestration)
│   └── sensor.ura_optimizer_house_summary ← NEW (house health + top findings)
├── URA: Optimization Coordinator  ← NEW DEVICE (detail view for everything)
│   ├── sensor.ura_optimizer_status
│   ├── sensor.ura_optimizer_findings
│   ├── sensor.ura_optimizer_room_health    (aggregate: worst score + per-room breakdown)
│   └── sensor.ura_optimizer_zone_health    (aggregate: worst score + per-zone breakdown)
├── URA: Presence Coordinator
├── URA: HVAC Coordinator
├── URA: Energy Coordinator
├── URA: Security Coordinator
├── URA: Safety Coordinator
├── URA: Notification Manager
├── URA: Music Following
├── URA: Zone Manager
│   ├── Zone: Entertainment
│   │   └── sensor.zone_1_optimization_health ← NEW (dedicated per-zone sensor)
│   ├── Zone: Master Suite
│   │   └── sensor.zone_master_suite_optimization_health
│   ├── Zone: Upstairs
│   │   └── sensor.zone_upstairs_optimization_health
│   └── ...
└── [30+ Room Devices]
    ├── Study A
    │   └── sensor.study_a_optimization_health ← NEW (dedicated per-room sensor)
    ├── Master Bedroom
    │   └── sensor.master_bedroom_optimization_health
    ├── Garage Hallway
    │   └── sensor.garage_hallway_optimization_health
    └── ...
```

### Sensors by Level

#### House Level (on Coordinator Manager device)

| Entity | State | Key Attributes |
|--------|-------|----------------|
| `sensor.ura_optimizer_house_summary` | "healthy" / "degraded" / "critical" | `house_score` (0-100), `dimensions` (state_machine, energy, security, prediction), `rooms_healthy`/`degraded`/`critical` counts, `zones_healthy`/`degraded` counts, `top_findings` (3 most severe), `worst_room`, `worst_zone` |

One sensor on the house device. Glance at it — if it's "healthy", everything is fine. If "degraded", the attributes tell you where.

#### Zone Level (dedicated sensor per zone device)

| Entity | State | Key Attributes |
|--------|-------|----------------|
| `sensor.{zone}_optimization_health` | Score 0-100 | `status` ("healthy"/"degraded"/"critical"), `dimensions` (room_aggregate, setpoint_compliance, vacancy_mgmt, pre_arrival, override_freq, duty_cycle), `degraded_dimensions` list, `room_scores` dict, `findings_count` |

Each zone gets its own sensor on its own device. The sensor lives where you'd expect — on the Zone: Entertainment device alongside the zone's other sensors.

#### Room Level (dedicated sensor per room device)

| Entity | State | Key Attributes |
|--------|-------|----------------|
| `sensor.{room}_optimization_health` | Score 0-100 | `status` ("healthy"/"degraded"/"critical"), `dimensions` (sensor_health, occupancy_accuracy, automation_responsiveness, config_behavior, comfort, energy_efficiency), `degraded_dimensions` list, `findings` (room-specific findings), `last_evaluated` |

Each room gets its own sensor on its room device. The sensor lives next to the room's other sensors (temperature, occupancy, etc.). Score of 92 = healthy. Score of 45 = go check the optimizer findings to see why.

#### Optimization Coordinator Device (detail/aggregate view)

| Entity | State | Key Attributes |
|--------|-------|----------------|
| `sensor.ura_optimizer_status` | "healthy" / "degraded" / "critical" | `house_score`, `open_findings_count`, `findings_today`, `last_evaluation`, `mode` (flag/agentic) |
| `sensor.ura_optimizer_findings` | Latest finding description | `findings`: last 20 findings [{level, room/zone, dimension, severity, description, timestamp}], `by_severity` counts, `by_level` counts |
| `sensor.ura_optimizer_room_health` | Worst room score | `rooms`: full per-room breakdown (score + 6 dimensions each), `healthy`/`degraded`/`critical` counts |
| `sensor.ura_optimizer_zone_health` | Worst zone score | `zones`: full per-zone breakdown (score + dimensions + room scores) |

This is the drill-down device. The house summary tells you "Study A is degraded." You come here to see exactly which dimensions are degraded and what the findings say.

### Beyond Sensors: Digests and Notifications

Sensors are passive — you have to go look. The optimizer should also **come to you**.

#### Immediate Notifications (via NM)

For severe findings that need attention now:

| Trigger | Severity | Channel | Example |
|---------|----------|---------|---------|
| Room health drops below 30 | CRITICAL | Pushover + TTS | "Study A health critical: temperature sensor unavailable for 2 hours, room running blind" |
| House state stuck (wrong state >30min) | HIGH | Pushover | "House state stuck on HOME but no one detected in any room for 35 minutes" |
| Security posture mismatch | HIGH | Pushover | "House is AWAY but security not armed — auto_follow toggle may be off" |
| Prediction accuracy below 50% for 3 days | MEDIUM | Companion App | "Energy forecast accuracy degraded to 42% — check weather entity" |
| High-value optimization found | MEDIUM | Companion App | "Zone 1 pre-cools 2h before peak but reaches setpoint in 45min — could save ~$0.30/day by reducing lead time" |

These use the existing NM infrastructure — `async_notify()` with appropriate severity routing. NM already handles quiet hours, dedup, cooldown, per-person channel preferences.

#### Daily Digest (via NM digest system)

NM already has morning/evening digest delivery (`CONF_NM_PERSON_DIGEST_MORNING`, `CONF_NM_PERSON_DIGEST_EVENING`). The optimizer produces a daily summary that feeds into this:

**Morning Digest Addition:**
```
🏠 URA Overnight Report
━━━━━━━━━━━━━━━━━━━━
House: 94/100 | 3 zones healthy
Rooms: 28/30 healthy
  ⚠ Garage Hallway: 62 (occupancy accuracy — motion sensor noisy)
  ⚠ Jaya Bedroom: 71 (sensor health — temp sensor unavailable)

Energy: $1.82 yesterday (↓12% vs 7-day avg)
HVAC: Zone 1 satisfaction 96%, Zone 2 88%

1 optimization opportunity:
  💡 Zone 1 pre-cool lead time could be reduced 2h→45min
```

**Implementation:** The optimizer writes a structured daily summary to a DB table (`optimization_daily_digest`). NM's digest builder queries this table when assembling the morning/evening digest. This keeps the two systems decoupled — the optimizer produces, NM consumes.

#### Weekly Report (new, optional)

A deeper analysis sent once per week:

```
📊 URA Weekly Report (Apr 1-7)
━━━━━━━━━━━━━━━━━━━━━━━━━━
Health Trend: 91→94 (improving)
Energy: $12.40 (↓8% vs prior week)
  Peak hours: $4.20 | Off-peak: $8.20
  Solar offset: 68%

Top 3 Findings This Week:
1. Garage Hallway false occupancy (fixed Apr 7) — was delaying AWAY by 30min
2. Master Bedroom fans activated unnecessarily during pre-arrival (fixed Apr 7)
3. Jaya Bedroom temp sensor intermittent — check Zigbee mesh

Predictions vs Actual:
  Energy forecast: 89% accurate (good)
  Occupancy patterns: 76% accurate (fair)
  HVAC pre-cool timing: 92% accurate (good)
```

### Interfaces Summary

#### Ingestion
| Source | Access Pattern | Frequency |
|--------|---------------|-----------|
| Room coordinator data | `hass.data[DOMAIN][entry_id].data` | Every 5min |
| Room config | `{**entry.data, **entry.options}` | On demand |
| Zone state | `zone_manager.zones[zone_id]` | Every 5min |
| House state | `coordinator_manager.house_state` | Every 5min |
| Activity log | DB query: recent window | Every 5min |
| Compliance/anomaly logs | DB query | Every 15min |

#### Output (Flag Mode)
| Channel | What | When |
|---------|------|------|
| **Optimizer device sensors** (5) | Health scores + findings | Every 5min update |
| **Room/zone breadcrumbs** | Single health attribute | Every 5min |
| **HA events** (`ura_optimization_finding`) | Individual findings | On discovery |
| **Activity log** | Optimizer decisions | On discovery |
| **HA logbook** | Via logbook.py formatter | On discovery |
| **NM immediate notification** | Severe findings | On critical/high |
| **NM daily digest** | Morning/evening summary | Scheduled |
| **NM weekly report** | Trend analysis | Weekly |

#### Output (Agentic Mode)
All of Flag Mode, plus:
| Action Type | Mechanism | Guardrail |
|-------------|-----------|-----------|
| Threshold adjustment | `hass.config_entries.async_update_entry()` | Numeric thresholds only, ±20% max |
| Service calls | `hass.services.async_call()` | 18-domain allowlist (same as AI rules) |
| Notification of action | Via NM | "Optimizer adjusted X because Y" — always sent |

#### Goal Injection
| Method | Storage | Example |
|--------|---------|---------|
| Config flow step | Config entry options | `async_step_optimization_goals()` |
| Service call | DB table `optimization_goals` | `universal_room_automation.add_goal` |
| Built-in (always active) | Hardcoded in optimizer | energy_cost, comfort, security |

---

## Phased Implementation

### Phase 1: Room Health Score + Findings Surface (~500 lines, 1 cycle)
- New file: `domain_coordinators/optimization.py`
- New DB table: `optimization_findings`
- Register as coordinator (priority 5, lowest) with its own device (`URA: Optimization Coordinator`)
- Every 5 minutes: evaluate each room across 6 dimensions
- **Sensors:** `sensor.ura_optimizer_status`, `sensor.ura_optimizer_findings`, `sensor.ura_optimizer_room_health`
- **Breadcrumbs:** Health score attribute on each room's occupied sensor
- **NM integration:** Immediate notification on critical room health drops
- Flag mode only
- **Leverages:** Room coordinator data, config entries, activity log, entity states, NM

### Phase 2: Zone + House Health + Daily Digest (~400 lines, 1 cycle)
- Extend optimization.py with zone and house evaluators
- Zone: aggregate room scores + HVAC metrics from ZoneManager
- House: aggregate zone scores + state machine + energy + security
- **Sensors:** `sensor.ura_optimizer_zone_health`, `sensor.ura_optimizer_house_health`
- **Breadcrumbs:** Health score on zone preset sensors, status on coordinator manager summary
- **Daily digest:** Write morning summary to `optimization_daily_digest` table, NM consumes for digest delivery
- **Leverages:** ZoneManager, coordinator_manager, house_state_machine, energy coordinator, NM digest system

### Phase 3: Prediction Validation + Weekly Report (~300 lines, 1 cycle)
- Add prediction tracking to optimization coordinator
- Compare predicted-vs-actual for: occupancy, energy, HVAC pre-cool, room transitions
- **Sensor:** Accuracy metrics added to `sensor.ura_optimizer_house_health` attributes
- **Weekly report:** Trend analysis + prediction accuracy + top findings, delivered via NM
- **Leverages:** PatternLearner, DailyEnergyPredictor, HVACOutcome, activity_log

### Phase 4: Rule-Based Optimization (~300 lines, 1 cycle)
- Tier 1 deterministic rule engine
- Built-in goals: energy cost, comfort, security posture
- Rules check room/zone/house data against goals
- **Output:** Optimization recommendations as findings (notable severity)
- **NM integration:** Notifications for high-value optimization opportunities (with estimated savings)
- **Leverages:** All data sources from Phases 1-3

### Phase 5: LLM-Assisted Analysis + Agentic Mode (~500 lines, 1-2 cycles)
- Tier 2 periodic batch analysis via Claude API
- Structured summary → Claude → structured findings + recommendations
- Agentic mode: action execution with guardrails (allowlisted, bounded, notified)
- User goal injection via config flow + service call
- **LLM enhances digest quality:** Weekly report gets Claude-generated prose instead of template
- **Leverages:** Claude API, existing AI rule patterns (v3.12.0)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Performance impact (evaluating all rooms every 5min) | Stagger room evaluation across cycles. Cache config reads. |
| False positives (flagging rooms that are fine) | Require sustained anomaly (not single-point). Use the existing z-score + MetricBaseline patterns. |
| Scope creep | Hard phase boundaries. Each phase is deployable independently. |
| LLM dependency (Phase 5) | Tier 1 always runs locally. Tier 2 is additive, graceful on failure. |
| Agentic mode safety | Allowlisted actions only. Numeric threshold adjustments bounded (±20% max). Notification on every autonomous action. |
| Interaction with Bayesian v4.0.0 | Complementary: Bayesian makes predictions, Optimization Coordinator validates them. Phase 3 is the bridge. |

---

## Relationship to Existing Systems

| Existing System | How Optimizer Uses It | How Optimizer Extends It |
|-----------------|----------------------|--------------------------|
| DecisionLogger | Reads decisions for compliance tracking | Logs its own optimization decisions |
| ComplianceTracker | Reads commanded-vs-actual for config-behavior alignment | Flags persistent non-compliance as findings |
| AnomalyDetector | Reads z-score anomalies | Contextualizes anomalies with room/zone/house health |
| MetricBaseline | Uses for statistical baselines | May register new metrics (health score trends) |
| Activity Log | Primary input for "what did URA do?" | Logs optimization findings/actions |
| PatternLearner | Reads room transition predictions | Validates prediction accuracy over time |
| DailyEnergyPredictor | Reads energy forecasts | Validates forecast accuracy, flags degradation |
| HVACOutcome | Reads daily zone satisfaction | Feeds zone health score |

The Optimization Coordinator is a **consumer** of all existing infrastructure, not a replacement. It adds the reasoning layer that connects data across levels and domains.
