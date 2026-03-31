# Universal Room Automation — Roadmap v11

**Version:** 11.0
**Current Production:** v3.19.1
**Last Updated:** March 30, 2026
**Status:** All domain coordinators complete. AI automation shipped. Bayesian intelligence next.

---

## EXECUTIVE SUMMARY

URA has evolved from a blueprint-based room automation system (v2.0) to a
whole-house intelligence platform (v3.19.1) with seven active domain
coordinators, AI-powered natural language automation, zone camera intelligence,
and 1243 tests across 48 Python files (~54,600 LOC).

Since Roadmap v10 (written at v3.8.9), the project has shipped 38 releases
covering: Energy E6 completion, Dashboard v2+v3, Notification Manager
inbound messaging + BlueBubbles/iMessage, AI Custom Automation (all 4
milestones), DB infrastructure repair, energy consumption model rewrite,
restart resilience, HVAC Zone Intelligence, BLE pre-arrival, and zone
camera face-confirmed arrivals.

**Current State (v3.19.1):**
- Entities: 90+ per room
- Tests: 1,243 passing
- Python files: 48 (21 main + 27 domain coordinators)
- LOC: ~54,600
- Response: 2-5 seconds (event-driven)
- Domain coordinators: 7 active (Presence, Safety, Security, NM, Energy, HVAC, Music Following)
- Toggle switches: 23 (1 master + 8 coordinator + 6 feature + 8 per-room)
- Architecture: Tri-level entries (Integration → Zones → Rooms) + Coordinator Manager

**Permanently Cut:**
- Circadian lighting (not needed — existing room automation handles light levels)
- Per-person temperature preferences (HVAC zone model makes this impractical)

**Next:**
- Bayesian Predictive Intelligence (v4.0.0) — the capstone feature

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

### Phase 7: Domain Coordinators (v3.6.0–v3.19.1) — COMPLETE
Feb–Mar 2026. The major engineering effort. Whole-house intelligence layer.

#### Cycle 0: Base Infrastructure (v3.6.0-c0 thru c0.4) — COMPLETE
BaseCoordinator, CoordinatorManager, ConflictResolver, Intent/CoordinatorAction
models, HouseState enum (9 states), HouseStateMachine, diagnostics framework,
per-coordinator enable/disable toggles, database tables (decision_log,
compliance_log, house_state_log, anomaly_log), Coordinator Manager + Zone
Manager as separate config entries.

#### Cycle 1: Presence Coordinator (v3.6.0-c1 thru v3.6.0.11) — COMPLETE
House state inference (9 states), zone presence modes, geofence integration,
census fusion, BLE integration, sleep hours config, hysteresis tuning.
Hardening: device area_id fallback, geofence any-state trigger, AWAY
hysteresis 300→30s, deferred retry.

#### Cycle 2/2.5: Safety Coordinator (v3.6.0-c2 thru v3.6.0.9) — COMPLETE
12 hazard types, bidirectional rate-of-change detection with seasonal
awareness, room-type humidity thresholds, alert deduplication, adaptive
rate-of-change (MetricBaseline, z-score, per-sensor learning), scoped
sensor discovery, glanceability sensors.

#### Cycle 3: Security Coordinator (v3.6.12–v3.6.16) — COMPLETE
Armed states, entry monitoring, lock/garage door management, 30-minute
lock sweep, census freshness checks, entry debounce, NM integration,
enable/disable toggle switch.

#### Cycle 4a: Notification Manager (v3.6.29–v3.6.35) — COMPLETE
5 channels: Pushover, Companion, WhatsApp, TTS, light patterns. Severity
routing, ack/cooldown/re-fire, digest (morning/evening), quiet hours.
Security NM integration, diagnostic sensors.

#### Cycle 4b: NM Inbound Messaging (v3.9.7) — COMPLETE
Response dictionary (ack/status/silence/help), safe word system for
CRITICAL alerts, 3-channel inbound (Companion/WhatsApp/Pushover), TTS ack
announcements, silence mechanism, inbound sensor, DB persistence + pruning.

#### Cycle 4b+: BlueBubbles/iMessage + Pushover Fix (v3.9.8) — COMPLETE
6th outbound channel: iMessage via BlueBubbles `send_message` service.
Webhook inbound handler (`_handle_bb_webhook`), person matching by
iMessage handle (email + phone last-10-digits), config flow UI for
channel + per-person handle, digest support, 13 new tests. Pushover
device targeting fix (`CONF_NM_PERSON_PUSHOVER_DEVICE` — `target` is
device name, not user key). Only remaining step: one-time operational
webhook registration on BlueBubbles server.

#### Mid-cycle Hardening (v3.6.14–v3.6.40) — COMPLETE
20-fix automation engine hardening, AutomationHealthSensor, Music Following
hardening + coordinator promotion, cover scheduling, config UX streamlining,
BaseCoordinator device_info identifier fix.

#### Cycle 5: Energy Coordinator (v3.7.0–v3.7.12) — COMPLETE
6 sub-cycles (E1–E5 + partial E6), 8 source files, 21 sensors:
TOU engine, battery strategy, solar forecast, pool optimizer, EV charger
control, SPAN/Emporia circuit monitoring, billing + cost tracking,
daily prediction + accuracy feedback + temperature regression.
Hardening: Envoy CT consumption, Envoy resilience, config flow, binary sensor.

#### Cycle 5 Completion: Energy E6 Return (v3.9.0–v3.9.13) — COMPLETE
All deferred E6 items shipped:
- **`pre_heat` constraint mode** — published during winter off-peak when
  forecast low near freeze, configurable offset (+2°F default)
- **`shed` constraint mode** — full cascade: pool→EV→smart plugs→HVAC,
  configurable shed offset (+5°F default)
- **`max_runtime_minutes`** — computed from TOU next transition, enforced
  by HVAC duty cycle windows (shed 50%, coast 75% of 20-min window)
- **Load shedding activation** — sustained grid import triggers cascade,
  auto-learned threshold (z-score after 300 samples, 90th percentile
  after 30 days, or fixed 5.0 kW default). Disabled by default (safety).
- **Peak import persistence** — `energy_peak_import` table, hourly save,
  startup restore, dirty flag throttling
- **Load shedding state persistence** — cascade level survives restarts
- **Energy situation enrichment** — constrained/optimizing/normal states

Additional E6-era releases: coordinator transparency, configurable offsets,
arrester enable/disable switch, per-zone preset sensors, HVAC observation
mode, battery/load shedding sensors, enhanced HVAC constraint handling.

#### Cycle 6: HVAC Coordinator (v3.8.0–v3.8.9) — COMPLETE
4 milestones (H1–H4), 8 source files:
- H1: Core + zones + presets + E6 signal reception
- H2: Override arrester + AC reset
- H3: Fan controller + cover controller (solar gain)
- H4: Predictive sensors + pre-conditioning
- Config flow UI with 7 tunable params
- BLE room occupancy (v3.8.8–v3.8.9): BLE persons drive room occupancy
  after motion/mmWave timeout, sparse BLE hardening for tier 2 rooms

#### AI Custom Automation (v3.10.0–v3.12.1) — COMPLETE
4 milestones, 95 tests:
- **M1 (v3.10.0):** Trigger infrastructure + automation chaining. 4 core
  trigger types (enter, exit, lux_dark, lux_bright), 3-zone hysteresis
  lux detection, config flow dropdown binding HA automations per trigger.
- **M2 (v3.12.0):** 12 coordinator signal triggers (9 house state + energy
  constraint + safety hazard + security event). Conditional signal
  subscriptions — handlers only subscribed when chains/rules configured.
  Signal dispatch wired from Safety + Security coordinators.
- **M3 (v3.12.0):** AI natural-language rules. Claude API parses ONCE to
  structured JSON at config time, zero AI cost at runtime. Person-specific
  filtering. 18-domain allowlist security (blocks homeassistant,
  shell_command, script, recorder). Conflict detection sensor.
- **M4 (v3.12.0):** AIAutomationStatusSensor diagnostics — active/inactive
  state, chain bindings, rule count, last trigger, conflict tracking.
- **v3.12.1:** Type safety hotfix (non-dict guards, module-level imports).

#### Census v2 (v3.10.1) — COMPLETE
Event-driven sensor fusion with hold/decay. Three-layer: cameras (face
freshness) + WiFi VLAN (guest phones) + BLE (arrival). Interior 15min hold
+ gradual decay, exterior 5min hold + instant drop. Asyncio lock, UTC
timestamps, sensor push. 62 new tests.

#### DB Infrastructure Repair (v3.13.0–v3.13.3) — COMPLETE
Per-table isolation (_create_table_safe), energy_snapshots auto-repair,
circuit_state table, tou_period migration, energy_history 13 columns,
cross-coordinator climate/occupancy helpers, serialized DB writes.
MetricBaseline integration: per-circuit z-score anomaly detection
(Welford's), load shedding z-score threshold, baseline persistence,
max_samples EWMA recency weighting, busy_timeout. 62 tests across
4 releases.

#### Energy Consumption Foundation Fix (v3.14.0–v3.14.2) — COMPLETE
5-sensor derived formula (replaced net grid import as total consumption),
battery_charged correction to prevent double-counting, piecewise SOC
battery taper, consumption-aware battery full time, 2 new forecast sensors,
battery-aware grid import model (solar timing, battery buffering, reserve
SOC), solar window timezone fix (UTC vs local date comparison).

#### Restart Resilience + NM Hardening (v3.15.0–v3.16.0) — COMPLETE
- v3.15.0: 3 new DB tables (envoy_cache, energy_midnight_snapshot,
  energy_state), full state persistence across HA restarts, Envoy cache
  with 4-hour staleness guard, load shedding 3-cycle grace period,
  serialized periodic DB writes.
- v3.15.1: Automatic guest mode from census (unidentified_count →
  GUEST state, time-based exit, sleep hour safety guard).
- v3.15.2: Thread safety (async_schedule_update_ha_state), isoformat
  guard, Python 3.9 annotations import.
- v3.15.3–v3.15.4: NM messaging kill switch (outbound suppression without
  teardown, live config refresh), inbound spam fix (unknown sender guards,
  context-gated replies), RestoreEntity for kill switch persistence,
  timer cleanup, light pattern task cancellation.
- v3.16.0: Circuit alert de-spam (HIGH not CRITICAL, unknown circuit
  filter, 50Wh delivery guard), self-contained kill switch state with
  bounded deferred NM sync (18 retries), BLE→motion source transition
  re-triggers entry automation with 60s cooldown.

#### HVAC Zone Intelligence (v3.17.0–v3.17.9) — COMPLETE
7 deliverables:
- D1: Zone vacancy management (2-tier grace: 15min normal, 5min constrained)
- D2: Zone-specific pre-conditioning (weather/solar banking/pre-arrival)
- D3: Person-to-zone mapping (SIGNAL_PERSON_ARRIVING)
- D4: Zone presence state machine (7 states)
- D5: Duty cycle enforcement (rolling 20-min window, shed 50%/coast 75%)
- D6: Max-occupancy failsafe (8h)
- D7: Diagnostic sensor
- Zone Intelligence toggle (ON=fine control, OFF=system-managed ramp)
- Review fixes: asyncio.Lock re-entrancy, elapsed time runtime tracking,
  fan cleanup, solar banking persistence, task tracking.
- Post-release (v3.17.4–v3.17.9): HVAC restart resilience, zone ID regex
  fix, off-restore fix, pre-dawn home state fix, AC reset toggle,
  config flow hardening.

#### Hardening Cycle (v3.18.0–v3.18.7) — COMPLETE
- v3.18.0: Fan control fixes, config flow save, zone sweep visibility,
  thread safety across all signal handlers.
- v3.18.1: @callback on 15 signal handlers (2310 thread-safety errors fixed).
- v3.18.2–v3.18.3: Options flow save fixes (Climate HVAC step).
- v3.18.4: DB locked fix, energy jitter guard, sensor log spam reduction.
- v3.18.5: Person-to-zone mapping in Zone Manager, sleep description fix.
- v3.18.6: BLE pre-arrival trigger + toggle + diagnostic sensor.
  Pre-arrival conditioning: -2°F offset, fan comfort bridge, 30-min timeout.
- v3.18.7: Config flow save fix (revert update listener to always reload).

#### Zone Camera Intelligence (v3.19.0–v3.19.1) — COMPLETE
- v3.19.0: Face-confirmed arrivals via Frigate integration. Face name →
  person entity mapping, 60-second per-person+zone cooldown, daily counter
  reset. Fires SIGNAL_PERSON_ARRIVING with source="camera_face" → triggers
  HVAC pre-arrival conditioning. Zone camera config, face freshness (30s).
- v3.19.1: Override thread-safety fix, diagnostics DB lock fix.

#### Comfort Features (absorbed into HVAC, v3.18.4) — COMPLETE
Comfort Coordinator was planned as C7 but deemed unnecessary as standalone
(~80% overlap with existing HVAC features). Absorbed into HVAC:
- **Shipped:** ComfortScoreSensor (0-100, temperature 40% + humidity 30%
  + occupancy 30%), TimeUncomfortableTodaySensor, AvgTimeToComfortSensor,
  HVACComfortViolationRiskSensor (low/medium/high from zone delta).
- **Permanently cut:** Circadian lighting, per-person temperature
  preferences (see below).

---

## PERMANENTLY CUT

These items were in earlier roadmaps but are permanently removed:

### Circadian Lighting
**Original plan:** Color temperature adjustment by time of day (2700K evening,
4500K midday). **Why cut:** Existing room-level automation already handles
light levels adequately. The marginal improvement doesn't justify the
complexity of managing color temperature state across all light entities,
especially with manual overrides.

### Per-Person Temperature Preferences
**Original plan:** Per-person temperature targets (e.g., John=68°F,
Jane=72°F), sensitivity profiles, fan preference. Applied via census/BLE
person identification. **Why cut:** The HVAC zone model (3 Carrier Infinity
zones, room-weighted aggregation) makes per-person preferences impractical
— zones serve multiple rooms with multiple people. The conflict resolution
complexity (whose preference wins?) exceeds the value. Zone-level presets
with house state awareness achieve most of the benefit.

### Portable Device Control
**Original plan:** Auto-control of space heaters, dehumidifiers by comfort
target. **Why cut:** Marginal value — most rooms don't have these devices.
Existing smart plug automation handles the simple on/off cases.

---

## OPERATIONAL ITEMS

### BlueBubbles Server Webhook Registration
**Status:** Code complete, needs one-time operational setup.
The HA-side webhook handler is fully implemented. The BlueBubbles server
running on Mac mini needs a webhook registered to push `new-message` events
to HA. Options: BB server UI or `POST /api/v1/webhook?password=<pw>` with
`{"url": "https://madronehaos.phalanxmadrone.com/api/webhook/universal_room_automation_bluebubbles_reply", "events": ["new-message"]}`.
BB server: `http://bluebubbles.phalanxmadrone.com`.

### Envoy Gateway Replacement
**Status:** Hardware failure 2026-03-26, replacement expected ~2026-04-01.
Energy Coordinator running on cached/stale data — PV production and battery
SOC are blind until the new Envoy is installed. No code changes needed;
the Envoy resilience layer (v3.7.3, v3.15.0) handles the offline gracefully
with cache + staleness guard + NM alerting.

---

## FUTURE ROADMAP

### v4.0.0 — Bayesian Predictive Intelligence
**Effort:** 20-30 hours
**Priority:** HIGH (capstone)
**Status:** Foundation partially built

Math-based probability predictions (not neural networks).

**Person-specific predictions:**
```python
P(John → Kitchen | 7AM, Weekday) = 0.85
P(Jane → Kitchen | 7AM, Weekday) = 0.45
```

**Key features:**
1. **Bayesian occupancy prediction** — per person per room, time-of-day
   and day-of-week segmented. Replace current frequency-based pattern
   learning (Counter) with proper posterior updates.
2. **Guest-aware training** — suppress prediction updates during guest mode
   to avoid contaminating learned patterns.
3. **Camera + BLE validated confidence boosting** — use zone camera
   intelligence (v3.19.0) face confirmations to boost prediction confidence.
4. **Energy consumption prediction integration** — extend the existing
   AccuracyTracker Bayesian adjustment (energy_forecast.py) with
   occupancy-weighted predictions.
5. **Uncertainty quantification** — predictions include confidence intervals,
   act only when P > threshold.
6. **Pre-emptive automation** — proactive room preparation (lights, climate)
   based on high-confidence occupancy predictions.

**Foundation already built:**
- Energy predictor AccuracyTracker with Bayesian adjustment factor
  (energy_forecast.py, 7-day rolling, ±0.3 dampened range)
- Temperature regression learning (30+ days, base + coeff model)
- Pattern learning module (pattern_learning.py) — frequency-based room
  transition prediction with multi-step path prediction (2-3 rooms ahead),
  confidence scoring, reliability classification. Explicitly defers
  Bayesian inference to v4.0.
- Database tables ready: `person_visits`, `room_transitions`,
  `person_presence_snapshots`, `parameter_beliefs`, `parameter_history`,
  `energy_daily`, `outcome_log`
- HVAC daily outcomes (hvac_predict.py) — zone satisfaction %, overrides,
  AC resets tracked daily

**Suggested milestones:**
1. **B1:** Bayesian model core — posterior update engine, time-of-day bins
   (6 periods), day-of-week grouping, prior initialization from existing
   frequency data in `room_transitions`
2. **B2:** Prediction sensors — per-person next-room prediction with
   confidence, whole-house occupancy forecast (1h/4h lookahead),
   prediction accuracy tracking sensor
3. **B3:** Pre-emptive actions — high-confidence prediction triggers
   room preparation (lights, HVAC pre-conditioning), configurable
   confidence threshold, integration with existing HVAC pre-arrival
4. **B4:** Energy integration — occupancy-weighted consumption prediction,
   improve daily forecast accuracy by incorporating predicted occupancy
   patterns into energy model

### v4.5.0 — Visual 2D Mapping
**Effort:** 30-40 hours
**Priority:** LOW
**Status:** Deferred

Floor plan with real-time person positions (from BLE + camera census),
camera coverage overlay, blind spot visualization, occupancy heatmaps.
Large effort for primarily visual value — deferred until core intelligence
is complete.

### Dashboard Iteration
**Effort:** Variable
**Priority:** LOW
**Status:** v2 shipped (v3.9.5), v3 built (dashboard-v3/), future polish TBD

Two dashboard builds exist:
- `dashboard/` (v1.0.0) — React + Vite + HAKit components, 7-tab glass
  morphism SPA
- `dashboard-v3/` (v3.0.0) — React + Vite (no HAKit components), rebuilt
  from v3.12.0 critique

Dashboard work is user-driven — no planned changes until specific needs arise.

---

## TECH DEBT & HARDENING QUEUE

Items that don't warrant their own version but should be addressed:

1. **Sensor placeholder TODOs** — 15 TODO/FIXME comments across sensor.py
   (11), button.py (2), binary_sensor.py (2). Mostly "Calculate from
   database" stubs in energy sensors and "Implement anomaly detection
   algorithm" placeholders. Low urgency — sensors return reasonable
   defaults.

2. **Load shedding user activation UX** — Load shedding cascade is fully
   implemented but defaults to disabled. No dashboard guidance on what
   enabling it means, what the cascade order is, or how thresholds work.
   Should add documentation or dashboard card before recommending users
   enable it.

3. **Energy observation mode UX** — Toggle exists but no dashboard guidance
   on what it means (sensors run, no actions taken).

4. **HVAC zone weight tuning** — Room weights are configurable but no
   guidance on how to set them. Could auto-learn from temperature sensor
   response times.

5. **Music Following device group duplication** — Historical issue from
   when MF was promoted from house-level feature to coordinator. Code-level
   `device_info` is now correct (inherits from BaseCoordinator), but
   orphaned device entries may exist in HA device registry. Low impact —
   cosmetic only.

6. **Roadmap doc cleanup** — ROADMAP_v9.md and PLANNING_v3.6.0_REVISED.md
   are obsolete. This v11 supersedes all prior roadmap documents.

---

## CODEBASE STATS

```
Production version:  v3.19.1 (March 30, 2026)
Total Python files:  48 (21 main + 27 domain coordinators)
Total LOC:           ~54,600
Tests:               1,243 passing
Entities per room:   90+
Domain coordinators: 7 active
  Presence (priority 60)
  Safety (priority 100)
  Security (priority 80)
  Notification Manager (shared service, 6 channels)
  Energy (priority 40)
  HVAC (priority 30)
  Music Following (priority 10)
Toggle switches:     23 (1 master + 8 coordinator + 6 feature + 8 per-room)
Database tables:     20+ (decision_log, compliance_log, house_state_log,
                     anomaly_log, energy_daily, energy_snapshots,
                     energy_peak_import, energy_midnight_snapshot,
                     energy_state, envoy_cache, circuit_state,
                     metric_baselines, occupancy_*, person_*, room_*,
                     parameter_beliefs, parameter_history, outcome_log)
Config entries:      Integration, Room (x N), Zone Manager, Coordinator Manager
Dashboards:          2 builds (v1 HAKit-based, v3 standalone React)
```

### Domain Coordinators File Map

```
domain_coordinators/                    (27 files, ~29,000 LOC)
├── __init__.py
├── base.py                  # BaseCoordinator, Intent, CoordinatorAction
├── manager.py               # CoordinatorManager, ConflictResolver
├── house_state.py           # HouseState enum, HouseStateMachine
├── signals.py               # Signal constants, EnergyConstraint dataclass
├── coordinator_diagnostics.py  # DecisionLogger, ComplianceTracker, AnomalyDetector
├── presence.py              # PresenceCoordinator, StateInferenceEngine, CameraFace
├── safety.py                # SafetyCoordinator, HazardType, RateOfChange
├── security.py              # SecurityCoordinator, armed states, lock sweep
├── notification_manager.py  # 6-channel delivery, routing, digest, quiet hours, inbound
├── music_following.py       # Music following coordinator
├── energy.py                # EnergyCoordinator (orchestrator, load shedding)
├── energy_tou.py            # TOU rate engine
├── energy_battery.py        # Battery strategy, SOC management
├── energy_pool.py           # Pool optimizer, VSF speed
├── energy_circuits.py       # SPAN/Emporia monitoring, anomaly detection
├── energy_forecast.py       # Daily predictor, accuracy tracker, Bayesian adjustment
├── energy_billing.py        # Cost calculator, bill cycle, bill prediction
├── energy_const.py          # Energy constants, rate tables
├── hvac.py                  # HVACCoordinator (orchestrator, zone intelligence)
├── hvac_zones.py            # Zone discovery, room aggregation, presence state machine
├── hvac_preset.py           # Preset manager, seasonal ranges
├── hvac_override.py         # Override arrester, AC reset
├── hvac_fans.py             # Fan controller, hysteresis, speed scaling
├── hvac_covers.py           # Cover controller, solar gain
├── hvac_predict.py          # Predictive sensors, pre-conditioning, comfort scoring
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
| v3.6.0–v3.6.40 | Feb–Mar 2026 | Coordinator infrastructure + Presence + Safety + Security + NM + MF hardening |
| v3.7.0–v3.7.12 | Mar 2026 | Energy Coordinator (E1–E5) |
| v3.8.0–v3.8.9 | Mar 2026 | HVAC Coordinator (H1–H4) + BLE room occupancy |
| v3.9.0–v3.9.13 | Mar 2026 | Energy E6, Dashboard v2, NM C4b inbound, peak import persistence |
| v3.10.0–v3.10.1 | Mar 2026 | AI Automation M1 (triggers + chaining), Census v2 |
| v3.12.0–v3.12.1 | Mar 2026 | AI Automation M2-M4 (signals, NL rules, diagnostics) |
| v3.13.0–v3.13.3 | Mar 2026 | DB infrastructure repair + MetricBaseline |
| v3.14.0–v3.14.2 | Mar 2026 | Energy consumption rewrite + battery-aware import |
| v3.15.0–v3.16.0 | Mar 2026 | Restart resilience, guest mode, NM hardening, kill switch |
| v3.17.0–v3.17.9 | Mar 2026 | HVAC Zone Intelligence (7 deliverables) + hotfixes |
| v3.18.0–v3.18.7 | Mar 2026 | Hardening cycle (thread safety, config flow, BLE pre-arrival) |
| v3.19.0–v3.19.1 | Mar 2026 | Zone Camera Intelligence (face-confirmed arrivals) |

---

## PRIORITY RANKING

1. **Bayesian Predictive Intelligence** (v4.0.0) — the capstone feature.
   Foundation built, pattern learning module ready for Bayesian upgrade.
   HIGH priority, large effort (20-30 hours).
2. **Dashboard iteration** — user-driven, as needs arise. LOW priority.
3. **Visual mapping** (v4.5.0) — deferred until Bayesian intelligence
   complete. LOW priority, very high effort.

---

**Roadmap v11.0**
**Updated:** March 30, 2026
**Supersedes:** ROADMAP_v10.md and all prior roadmap/planning documents
**Next Update:** After Bayesian Intelligence milestones begin
