# Universal Room Automation — Roadmap v10

**Version:** 10.0
**Current Production:** v3.8.9
**Last Updated:** March 7, 2026
**Status:** Domain coordinators complete (6 of 7). Energy E6 return + Comfort C7 remain.

---

## EXECUTIVE SUMMARY

URA has evolved from a blueprint-based room automation system (v2.0) to a
sophisticated whole-house intelligence platform (v3.8.9) with six active domain
coordinators, 686+ tests, 90+ entities per room, and a 26-file domain
coordinators subsystem (~5,000 LOC). This roadmap captures the completed work,
the two remaining coordinator items, and the path beyond.

**Current State (v3.8.9):**
- Entities: 90+ per room
- Tests: 686 passing
- Response: 2-5 seconds (event-driven)
- Domain coordinators: 6 active (Presence, Safety, Security, Notification Manager, Energy, HVAC)
- Architecture: Tri-level entries (Integration → Zones → Rooms) + Coordinator Manager

**Immediate Next:**
- Energy E6 return (deferred HVAC constraint enrichment + load shedding)
- Comfort Coordinator C7 (circadian lighting, per-person preferences, comfort scoring)

---

## COMPLETED MILESTONES

### Phase 1-4: Foundation through Zones (v2.0–v3.1.5) — COMPLETE
Nov–Dec 2025. Room automation core, config flow, dual-entry architecture,
zone aggregation, safety alerts, energy monitoring, water leak detection.

### Phase 5: Enhanced Presence (v3.2.0–v3.2.9) — COMPLETE
Dec 2025–Jan 2026. Bermuda BLE person tracking framework, multi-person
support, room/zone/integration sensors, confidence scoring, decay logic,
event-driven updates. 178 tests.

### Phase 6: Camera Intelligence (v3.5.0–v3.5.3) — COMPLETE
Feb 2026. Camera census (UniFi + Frigate + Reolink + Dahua), per-camera
binary counting, face recognition, transit validation, perimeter alerting,
zone person aggregation, privacy-first design.

### Phase 7: Domain Coordinators (v3.6.0–v3.8.9) — IN PROGRESS
Feb–Mar 2026. The major engineering effort. Builds the whole-house
intelligence layer above per-room automation.

#### Cycle 0: Base Infrastructure (v3.6.0-c0 thru c0.4) — COMPLETE
- BaseCoordinator, CoordinatorManager, ConflictResolver
- Intent/CoordinatorAction models, Severity enum
- HouseState enum (9 states), HouseStateMachine
- Diagnostics framework (DecisionLogger, ComplianceTracker, AnomalyDetector)
- Per-coordinator enable/disable toggles
- Database: decision_log, compliance_log, house_state_log, anomaly_log
- Coordinator Manager + Zone Manager as separate config entries

#### Cycle 1: Presence Coordinator (v3.6.0-c1 thru v3.6.0.11) — COMPLETE
- House state inference (AWAY/ARRIVING/HOME_DAY/HOME_EVENING/HOME_NIGHT/
  SLEEP/WAKING/GUEST/VACATION)
- Zone presence modes (away/occupied/sleep/unknown) with select overrides
- Geofence integration, census fusion, BLE integration
- Sleep hours config, hysteresis tuning
- Hardening: device area_id fallback, geofence any-state trigger,
  AWAY hysteresis 300→30s, deferred retry

#### Cycle 2/2.5: Safety Coordinator (v3.6.0-c2 thru v3.6.0.9) — COMPLETE
- 12 hazard types (smoke, fire, CO, water leak, flooding, freeze, overheat,
  HVAC failure, high/low humidity, high CO2, high TVOC)
- Bidirectional rate-of-change detection with seasonal awareness
- Room-type humidity thresholds (bathroom vs normal)
- Alert deduplication with per-severity suppression windows
- Adaptive rate-of-change (MetricBaseline, z-score, per-sensor learning)
- Scoped sensor discovery (global config selectors)
- Glanceability sensors

#### Cycle 3: Security Coordinator (v3.6.12–v3.6.16) — COMPLETE
- Armed states, entry monitoring, lock/garage door management
- 30-minute lock sweep (skips home_day), census freshness checks
- Entry debounce, services.yaml, NM integration
- Enable/disable toggle switch entity

#### Cycle 4: Notification Manager (v3.6.29–v3.6.35) — COMPLETE
- 5 channels: Pushover, Companion, WhatsApp, TTS, light patterns
- Severity routing (CRITICAL/HIGH/MEDIUM/LOW → channel mapping)
- Ack/cooldown/re-fire, digest (morning/evening), quiet hours
- Security NM integration (hazard_type, location fields)
- Diagnostic sensors (anomaly, delivery rate, diagnostics)

#### Mid-cycle hardening (v3.6.14–v3.6.40) — COMPLETE
- v3.6.14: 20-fix automation engine hardening
- v3.6.17: AutomationHealthSensor (per-room composite diagnostic)
- v3.6.19-21: Music Following hardening (cooldown, ping-pong, BLE tightening)
- v3.6.24: Music Following Coordinator (configurable tuning)
- v3.6.36: BaseCoordinator device_info identifier fix
- v3.6.37-40: Cover scheduling, config UX streamlining, dashboard work

#### Cycle 5: Energy Coordinator (v3.7.0–v3.7.12) — MOSTLY COMPLETE
6 sub-cycles, 8 source files, 21 sensors:

| Sub-Cycle | Scope | Status |
|-----------|-------|--------|
| E1 | TOU engine + battery strategy + solar forecast | DONE (v3.7.0) |
| E2 | Pool optimizer + EV charger control + smart plugs | DONE (v3.7.0) |
| E3 | SPAN/Emporia circuit monitoring + anomaly detection | DONE (v3.7.0) |
| E4 | Billing + cost tracking + bill prediction | DONE (v3.7.11) |
| E5 | Daily prediction + accuracy feedback + temp regression | DONE (v3.7.12) |
| **E6** | **HVAC constraints + covers + load shedding** | **PARTIAL** |

**E6 status detail:**
- SIGNAL_ENERGY_CONSTRAINT dispatcher — DONE (wired in v3.8.0)
- EnergyConstraint dataclass with all fields — DONE
- Basic constraint modes (normal/pre_cool/coast) — DONE
- Forecast high temp in constraint — DONE
- `pre_heat` constraint mode — NOT DONE (HVAC predictor handles pre-heat
  independently via weather, but Energy doesn't publish a pre_heat constraint)
- `shed` constraint mode — NOT DONE (load shedding priority is stubbed,
  `_load_shedding_enabled = False`)
- `max_runtime_minutes` field — NOT DONE (exists in dataclass, always None)
- Cover Controller for solar gain — DONE (moved to HVAC, `hvac_covers.py`)
- Load shedding priority order — STUBBED (data structures exist, execution
  gated behind `load_shedding_enabled = False`)

Hardening releases: v3.7.1 (import fix), v3.7.2 (Envoy CT consumption),
v3.7.3 (Envoy resilience), v3.7.4 (config flow + Envoy binary sensor),
v3.7.5-v3.7.12 (forecast improvements, DB accuracy, temp regression)

#### Cycle 6: HVAC Coordinator (v3.8.0–v3.8.7) — COMPLETE
4 milestones, 8 source files:

| Milestone | Scope | Version |
|-----------|-------|---------|
| H1 | Core + zones + presets + E6 signal | v3.8.0-v3.8.2 |
| H2 | Override arrester + AC reset | v3.8.3 |
| H3 | Fan controller + cover controller | v3.8.4 |
| H4 | Predictive sensors + pre-conditioning | v3.8.5 |

Plus: v3.8.6 (config flow UI), v3.8.7 (AC reset timeout wiring fix)

Key sub-modules: hvac.py, hvac_zones.py, hvac_preset.py, hvac_override.py,
hvac_fans.py, hvac_covers.py, hvac_predict.py, hvac_const.py

Features: 3-zone Carrier Infinity management, room-weighted aggregation,
seasonal preset ranges, energy constraint response (coast/pre_cool),
event-driven override detection with two-tier severity, stuck cycle reset,
ceiling fan hysteresis + speed scaling + occupancy gating, common area cover
solar gain logic, pre-cool/pre-heat engine, daily outcome tracking,
forecast accuracy feedback, config flow with 7 tunable params.

#### Post-HVAC: BLE Room Occupancy (v3.8.8–v3.8.9)
- v3.8.8: BLE persons from person_coordinator now drive room occupancy
  after motion/mmWave timeout. `occupancy_source` and `ble_persons`
  attributes on all occupied binary sensors. Failsafe bypass fix.
- v3.8.9: Sparse BLE hardening. Tier 2 rooms (shared scanner via
  CONF_SCANNER_AREAS) require recent motion/mmWave confirmation
  before BLE can create occupancy. Cached tier classification.

---

## ACTIVE WORK

### Energy E6 Return — v3.9.x
**Effort:** 3-5 hours
**Priority:** HIGH
**Dependencies:** HVAC Coordinator complete (DONE)

Now that the HVAC Coordinator exists and consumes SIGNAL_ENERGY_CONSTRAINT,
the deferred E6 items can be completed. The HVAC coordinator defined what it
needs — Energy can now publish richer constraints.

**What remains:**

1. **`pre_heat` constraint mode** — Energy publishes pre_heat during winter
   off-peak when forecast low is near freeze and off-peak is ending. Currently
   HVAC's predictor handles pre-heat independently via weather data, but the
   Energy→HVAC signal path is one-directional (pre_cool only). Wiring pre_heat
   through Energy gives TOU-awareness and SOC-awareness to heating decisions.

2. **`shed` constraint mode** — When grid outage or extreme peak stress,
   Energy tells HVAC to switch to fan_only or off. Currently stubbed
   (`_load_shedding_enabled = False`). The data structures and priority
   order exist but execution is gated.

3. **`max_runtime_minutes` field** — Exists in EnergyConstraint dataclass,
   always set to None. Intended to limit how long a coast/shed can run before
   reverting to normal. HVAC should implement the timeout; Energy sets the limit.

4. **Load shedding activation path** — The priority order is designed
   (pool→EV→infinity edge→pool heater→HVAC setback→circuits) but never
   executes. Need: an activation trigger (grid outage, SOC critically low,
   extreme peak pricing), an observation-mode-aware execution path, and
   NM notifications for shedding events.

5. **Energy situation enrichment** — `_update_energy_situation` currently only
   uses TOU period + load shedding flag. Could incorporate: SOC trend, solar
   forecast vs actual divergence, grid outage detection.

### Comfort Coordinator C7 — v3.10.x
**Effort:** 3-5 hours
**Priority:** MEDIUM
**Dependencies:** Presence (DONE), Energy (DONE), HVAC (DONE)

Per the HVAC Coordinator plan, C7 is deliberately thin because HVAC absorbed
fan coordination, cover control, and zone climate management. What remains:

1. **Per-person comfort preferences** — temperature preferences, sensitivity
   (sensitive/normal/tolerant), fan preference. Applied when person identified
   in room via census/BLE.

2. **Comfort scoring** — multi-factor 0-100 score per room:
   temperature (40%), humidity (25%), air quality (25%), lighting (10%).
   Configurable weights.

3. **Circadian lighting** — color temperature adjustment by time of day for
   configured lights. Warm (2700K) evening/night, cool (4500K) midday.

4. **Portable device control** — space heaters, dehumidifiers. Auto-on/off
   by comfort target vs current conditions. Marginal value (most homes don't
   have these).

5. **HVAC signaling** — when room-level devices can't achieve comfort target,
   publish `SIGNAL_COMFORT_REQUEST` for HVAC to adjust zone setpoints. HVAC
   denial handling (DENIED_ENERGY, PARTIAL).

6. **Sensors:** `sensor.ura_comfort_score` (whole-house weighted average),
   `sensor.ura_comfort_bottleneck` (worst room + limiting factor),
   per-room comfort scores as attributes.

**Decision point:** C7 may be deferred further or built minimally (scoring +
circadian only) depending on actual need. HVAC already handles the heavy
lifting for thermal comfort.

---

## FUTURE ROADMAP

### v3.4.0 — AI Custom Automation
**Effort:** 12-15 hours
**Priority:** HIGH (game-changer)
**Status:** Planned, not started

Natural language room customization. User types rules in plain English,
Claude API parses ONCE to structured JSON, cached in entry.options, runtime
executes with zero AI cost.

**Examples:**
```
"Use sensor.bed_pressure for occupancy. When over 50 lbs for 5 min,
mark the room occupied. Don't turn off lights when the TV is on."

"When John is home, temperature 68. When Jane is home, 72.
When guests are present, 70."
```

**Architecture:** Config flow text area → Claude API parse → structured rules
in entry.options → rule execution engine (standard HA service calls).

**Enhanced by completed infrastructure:**
- Person identity from census/BLE (v3.5.x + v3.8.8)
- House state from Presence Coordinator
- Energy awareness from Energy Coordinator
- HVAC zone context from HVAC Coordinator

### v4.0.0 — Bayesian Predictive Intelligence
**Effort:** 20-30 hours
**Priority:** HIGH (capstone)
**Status:** Planned, not started

Math-based probability predictions (not neural networks).

**Person-specific predictions:**
```python
P(John → Kitchen | 7AM, Weekday) = 0.85
P(Jane → Kitchen | 7AM, Weekday) = 0.45
```

**Key features:**
- Bayesian inference for occupancy prediction per person per room
- Guest-aware training (suppress predictions during guest mode)
- Camera + BLE validated confidence boosting
- Energy consumption prediction integration (already started in E5)
- Uncertainty quantification (predictions include confidence intervals)

**Foundation already built:**
- Energy predictor (v3.7.12) has Bayesian accuracy tracking + temp regression
- Person tracking (v3.2.x) has room transition history in DB
- Census (v3.5.x) provides person count validation
- Occupancy patterns stored in SQLite (daily/weekly aggregates)

### v4.5.0 — Visual 2D Mapping
**Effort:** 30-40 hours
**Priority:** LOW
**Status:** Deferred

Floor plan with real-time person positions, camera coverage overlay,
blind spot visualization, occupancy heatmaps.

---

## TECH DEBT & HARDENING QUEUE

Items that don't warrant their own version but should be addressed:

1. **Music Following device group duplication** — MF device appears in both
   integration and CM groups. Requires understanding MF init lifecycle.

2. **Roadmap/plan doc staleness** — ROADMAP_v9.md, PLANNING_v3.6.0_REVISED.md
   show wrong cycle statuses. This v10 supersedes both.

3. **Load shedding test coverage** — data structures exist, execution is
   stubbed. No tests cover the activation path.

4. **Energy observation mode UX** — toggle exists but no dashboard guidance
   on what it means.

5. **HVAC zone weight tuning** — room weights are configurable but no
   guidance on how to set them. Could auto-learn from temperature sensor
   response times.

---

## CODEBASE STATS

```
Production version:  v3.8.9 (March 7, 2026)
Total Python files:  40+
Total LOC:           ~25,000
Tests:               686 passing
Entities per room:   90+
Domain coordinators: 6 active + 1 planned
  Presence (priority 60)
  Safety (priority 100)
  Security (priority 80)
  Notification Manager (shared service)
  Energy (priority 40)
  HVAC (priority 30)
  [Comfort (priority 20) — planned]
Coordinator files:   26 files in domain_coordinators/
Database tables:     15+ (decision_log, compliance_log, house_state_log,
                     anomaly_log, energy_daily, occupancy_*, person_*, etc.)
Config entries:      Integration, Room (x N), Zone Manager, Coordinator Manager
```

### Domain Coordinators File Map

```
domain_coordinators/
├── __init__.py
├── base.py                  # BaseCoordinator, Intent, CoordinatorAction
├── manager.py               # CoordinatorManager, ConflictResolver
├── house_state.py           # HouseState enum, HouseStateMachine
├── signals.py               # Signal constants, EnergyConstraint dataclass
├── coordinator_diagnostics.py  # DecisionLogger, ComplianceTracker, AnomalyDetector
├── presence.py              # PresenceCoordinator, StateInferenceEngine
├── safety.py                # SafetyCoordinator, HazardType, RateOfChange
├── security.py              # SecurityCoordinator, armed states, lock sweep
├── notification_manager.py  # 5-channel delivery, routing, digest, quiet hours
├── music_following.py       # Music following coordinator
├── energy.py                # EnergyCoordinator (orchestrator)
├── energy_tou.py            # TOU rate engine
├── energy_battery.py        # Battery strategy, SOC management
├── energy_pool.py           # Pool optimizer, VSF speed
├── energy_circuits.py       # SPAN/Emporia monitoring, anomaly detection
├── energy_forecast.py       # Daily predictor, accuracy tracker
├── energy_billing.py        # Cost calculator, bill cycle, bill prediction
├── energy_const.py          # Energy constants, rate tables
├── hvac.py                  # HVACCoordinator (orchestrator)
├── hvac_zones.py            # Zone discovery, room aggregation
├── hvac_preset.py           # Preset manager, seasonal ranges
├── hvac_override.py         # Override arrester, AC reset
├── hvac_fans.py             # Fan controller, hysteresis, speed scaling
├── hvac_covers.py           # Cover controller, solar gain
├── hvac_predict.py          # Predictive sensors, pre-conditioning
└── hvac_const.py            # HVAC constants
```

---

## VERSION HISTORY (condensed)

| Version Range | Period | Focus |
|---------------|--------|-------|
| v2.0–v2.4 | Nov 2025 | Foundation, config flow, options flow |
| v3.0–v3.1.5 | Nov–Dec 2025 | Dual-entry, zones, aggregation, safety alerts |
| v3.2.0–v3.2.9 | Dec 2025–Jan 2026 | BLE person tracking, event-driven arch |
| v3.3.0–v3.3.5 | Jan 2026 | Music following, cross-room coordination |
| v3.5.0–v3.5.3 | Feb 2026 | Camera census, transit validation, perimeter |
| v3.6.0-c0–c0.4 | Feb 2026 | Coordinator base infrastructure + diagnostics |
| v3.6.0-c1–c1.1 | Feb 2026 | Presence Coordinator + zone modes |
| v3.6.0-c2–v3.6.0.11 | Feb–Mar 2026 | Safety + presence hardening |
| v3.6.12–v3.6.16 | Mar 2026 | Security Coordinator |
| v3.6.17–v3.6.28 | Mar 2026 | Automation health, music hardening, covers |
| v3.6.29–v3.6.35 | Mar 2026 | Notification Manager |
| v3.6.36–v3.6.40 | Mar 2026 | Device fixes, covers, config UX |
| v3.7.0–v3.7.12 | Mar 2026 | Energy Coordinator (E1–E5) |
| v3.8.0–v3.8.7 | Mar 2026 | HVAC Coordinator (H1–H4 + config flow) |
| v3.8.8–v3.8.9 | Mar 2026 | BLE room occupancy + sparse hardening |

---

## PRIORITY RANKING

1. **Energy E6 return** (v3.9.x) — complete the deferred constraint modes
   and load shedding activation. HIGH priority because HVAC is now ready
   to consume richer constraints.
2. **Comfort C7** (v3.10.x) — thin coordinator: scoring + circadian +
   per-person preferences. MEDIUM priority, deferred if not needed.
3. **AI Custom Automation** (v3.4.0) — game-changer for room customization.
   HIGH priority but large effort.
4. **Bayesian Predictions** (v4.0.0) — capstone intelligence. Foundation
   already partially built in Energy predictor.
5. **Visual Mapping** (v4.5.0) — LOW priority, very high effort.

---

**Roadmap v10.0**
**Updated:** March 7, 2026
**Supersedes:** ROADMAP_v9.md, PLANNING_v3.6.0_REVISED.md cycle statuses
**Next Update:** After Energy E6 return or Comfort C7 deployment
