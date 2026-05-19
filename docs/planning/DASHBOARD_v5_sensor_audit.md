# Dashboard v5.0 (P6 Fulcrum) — Sensor Gap Audit

**Date:** 2026-05-19
**Audit run:** Explore agent against P6 prototype + URA source (169 sensor classes inventoried)
**Purpose:** Categorize every concrete data value in the P6 prototype to identify Python mini-cycles required before React tab rebuilds (D3-D7 in PLANNING_v5.x_dashboard_v4_react_port.md)

---

## Distribution

| Category | Count | Description |
|---|---|---|
| **(a) EXISTS** | ~40 | Live URA sensor today; React just wires `useEntity` |
| **(b) ATTRIBUTE ADD** | ~10 | Existing sensor needs one-line `extra_state_attributes` addition |
| **(c) NEW SENSOR** | ~6 sensor families | Net-new sensor class + computation needed |
| **(d) PROTOTYPE FICTION** | ~6 | UI affordance or external integration; document as stub or external dep |

**Total Python work before React rebuild:** ~470 LoC across 3-4 mini-cycles, ~12-15h elapsed.

---

## Per-Tab Audit

### Tab: Home

| Value | Status | Notes |
|---|---|---|
| House mode (`home_day`) | (a) EXISTS | `HouseStateSensor` / `IntegrationHouseStateSensor` |
| Routine confidence (87%) | (a) EXISTS | `PersonRoutineStatusSensor.confidence`; verify field name |
| Active anomaly count | (a) EXISTS | `URARecentAnomaliesSensor` (v4.6.3) |
| 5/5 healthy coordinators | (b) ADD | `CoordinatorSummarySensor` + `health_status` dict |
| Decisions today | (c) NEW | Aggregate per-coordinator decision count; ~50 LoC |
| BLE+motion 92% confidence | (a) EXISTS | `PersonLocationSensor` fusion confidence |

### Tab: House

| Value | Status | Notes |
|---|---|---|
| 8 rooms occupied · 11 idle | (a) EXISTS | `RoomsOccupiedSensor` |
| 3 zones with motion | (c) NEW | Count zones with recent motion; ~30 LoC |
| Range 71°–76° | (a) EXISTS | `ClimateDeltaSensor` high/low |
| Main: 12 · Kids: 6 · Master: 5 | (b) ADD | `RoomsOccupiedSensor` + `per_zone_breakdown` dict |

### Tab: Zones

| Value | Status | Notes |
|---|---|---|
| Rail chip "Zones 5" | (a) EXISTS | Zone manager count |
| 3/5 rooms occupied (per zone) | (a) EXISTS | Per-zone aggregation |
| 12/18 lights on | (a) EXISTS | `LightsOnCountSensor` per zone |
| Coast mode badge | (a) EXISTS | `HVACArresterStatusSensor` |
| Wake zone button | (d) FICTION | UI control; no sensor needed |

### Tab: Rooms

| Value | Status | Notes |
|---|---|---|
| Rail chip "Rooms 19" | (a) EXISTS | Room registry count |
| 4/6 lights, 5/5 lights | (a) EXISTS | `LightsOnCountSensor` per room |
| "idle 4h" | (b) ADD | Room sensor + `idle_duration` attribute |
| "Oji" / "Ziri" room badges | (b) ADD | Room sensor + `current_persons` array |

### Tab: Energy

| Value | Status | Notes |
|---|---|---|
| $2.34 today, $4.82 cost | (a) EXISTS | `EnergyCoordCostTodaySensor` |
| 28.4 kWh solar today | (a) EXISTS | Solar production sensor |
| Battery 78% discharging | (a) EXISTS | Battery + direction from EC |
| Solar/battery/grid breakdown | (b) ADD | `WholeHousePowerSensor` + `source_breakdown` dict |
| TOU mid-peak | (a) EXISTS | `EnergyTOUPeriodSensor` |
| Demand 88% (vs grid cap) | (c) NEW | Demand-vs-cap calculation; ~40 LoC |
| Active pre-cool: Kids zone | (a) EXISTS | `HVACZoneStatusSensor` mode |

### Tab: HVAC

| Value | Status | Notes |
|---|---|---|
| System demand 64% | (c) NEW | Aggregate HVAC load vs capacity; ~50 LoC |
| Cool mode | (a) EXISTS | `HVACModeSensor` |
| Per-zone 72° setpoint | (a) EXISTS | `HVACZoneStatusSensor` |
| Coast / pre-cool badges | (a) EXISTS | Derived from mode tracking |
| Hot/cold limits 82°/62° | (b) ADD | `HVACModeSensor` + `zone_limits` dict |

### Tab: Presence

| Value | Status | Notes |
|---|---|---|
| Rail chip "Presence 3/4" | (a) EXISTS | `URAIdentifiedPersonsInHouseSensor` |
| Fusion confidence 92/88/95% | (a) EXISTS | Per-person confidence |
| Next likely: Master Bed 22:15 | (a) EXISTS | `PersonLikelyNextRoomSensor` |
| Music following 3 rooms | (a) EXISTS | `MusicFollowingActiveRoomsSensor` |
| ETA home / commute | **KILLED 2026-05-19** | User directive — remove from design, don't ship even as stub |
| Bedtime routine 19:30 | (a) EXISTS | `PersonRoutineStatusSensor.next_event` |
| Z=2.4 ADVISORY anomaly | (a) EXISTS | `PresenceAnomalySensor` |

### Tab: Security

| Value | Status | Notes |
|---|---|---|
| Disarmed / arm mode | (a) EXISTS | `SecurityArmedStateSensor` |
| 4/4 locked | (a) EXISTS | Lock count from device registry |
| 9 cameras recording | (a) EXISTS | Camera count from device registry |
| Garage opened 17:54 | (a) EXISTS | `SecurityLastEntrySensor` |
| Open entries | (a) EXISTS | `SecurityOpenEntriesSensor` |

### Tab: Safety (inherited from P4)

| Value | Status | Notes |
|---|---|---|
| 0 active hazards | (a) EXISTS | `SafetyActiveHazardsSensor` |
| 12 detectors OK | (a) EXISTS | `SafetyAffectedRoomsSensor` related |
| Kitchen smoke/CO ppm | (b) ADD | Detector sensors + `smoke_ppm`, `co_ppm`, `battery_percent`, `last_test` (verify; some may exist) |
| Hazard guard policy | (d) FICTION | Policy statement; no sensor |
| Water leak detector states | (a) EXISTS | Per-detector device integration |
| 3 events today auto-dismissed | (b) ADD | New aggregator: `events_today_count` + `auto_dismissed_count` |

### Tab: Diagnostics

| Value | Status | Notes |
|---|---|---|
| URA version + PRAGMA | (a) EXISTS | Already in config + DB metadata |
| 5/5 coordinators healthy | (b) ADD | `CoordinatorSummarySensor` + `status_per_coordinator` |
| Uptime 6d 14h | (a) EXISTS | `URASetupDurationSensor` (v4.6.10) + HA startup time |
| Decisions today (per coord) | (c) NEW SET | 5 sensors × 15 LoC = ~75 LoC |
| Success rate (per coord) | (c) NEW SET | 5 sensors × 20 LoC = ~100 LoC |
| Override freq (per coord) | (c) NEW SET | 5 sensors × 15 LoC = ~75 LoC |
| Last decision timestamps | (a) EXISTS | `LastAutomationActionSensor`; verify per-coord granularity |
| Active anomalies 2 | (a) EXISTS | `URARecentAnomaliesSensor` |
| DB size 812 MB | (b) ADD | New diagnostic sensor surfacing DB metrics; ~20 LoC |
| Write queue 0 pending | (d) FICTION | Internal state; stub unless critical |

### Rail chips

| Chip | Value | Status |
|---|---|---|
| Zones | 5 | (a) EXISTS |
| Rooms | 19 | (a) EXISTS |
| Presence | 3/4 | (a) EXISTS |

---

## Recommended Python mini-cycles (ordered)

### Cycle A — Attribute Adds (v4.6.11 add-on, ~70 LoC, 2-3h)
Roll into the v4.6.11 polish cycle already filed in BACKLOG.

- `CoordinatorSummarySensor`: `health_status` + `status_per_coordinator` dicts
- `RoomsOccupiedSensor`: `per_zone_breakdown` dict
- Room occupancy sensor: `idle_duration` + `current_persons` array
- `WholeHousePowerSensor`: `source_breakdown` (solar/battery/grid)
- `HVACModeSensor`: `zone_limits` dict
- Safety detector sensors: audit for `smoke_ppm` / `co_ppm` / `battery_percent` / `last_test` — add if missing
- New `SafetyEventsSummarySensor`: `events_today_count` + `auto_dismissed_count`

### Cycle B — Net-New Aggregator Sensors (Tier 1, ~120 LoC, 4-5h)
**Required before D3 Home tab + Energy + HVAC tabs.**

- `ZoneMotionEventCountSensor` — count zones with motion in last 5m (~30 LoC)
- `HouseSystemDemandSensor` — HVAC load as % of system capacity (~50 LoC)
- `EnergyGridDemandSensor` — demand as % of grid cap config (~40 LoC)

### Cycle C — Coordinator Telemetry Sensor Set (Tier 1, ~80-100 LoC, 3-4h)

**Revised 2026-05-19** after discovering `ura_activity_log` table already captures the underlying data via `activity_logger.py`. The original ~280 LoC estimate assumed new logging infrastructure; actual work is just sensor classes querying the existing table.

- Per-coordinator decision count sensors (5 × 12 LoC = 60) — `COUNT(*) WHERE coordinator=? AND DATE(timestamp)=DATE('now')`
- Per-coordinator override frequency sensors (5 × 12 LoC = 60) — same with `action LIKE 'override%'` filter
- **Success rate** — `ura_activity_log` schema doesn't track outcome explicitly. Options:
  - (i) Proxy via `importance` field (info=success, warning=partial, error=failure) — ~5 LoC per coord; assumption that emitters use importance consistently
  - (ii) Add `outcome` column to `ura_activity_log` — needs Tier 2-DB schema migration (~80 LoC + migration)
  - **Decision deferred to Cycle C planning** — recommend option (i) for v5.0 ship + filing option (ii) as v5.1+ telemetry-quality improvement
- DB size sensor (~20 LoC)
- Last decision timestamp per coord (~10 LoC if needed beyond existing `LastAutomationActionSensor`)

### Stubs / External (deferred to v5.1+ or never)

- **Wake zone button** — UI action, no sensor
- **ETA home / commute time** — requires external API integration; ship as static "—" placeholder in D3, file enhancement for v5.1
- **Write queue pending depth** — internal queue state; stub unless critical for ops

---

## Critical-path implications for dashboard cycle order

Original plan:
- D3 Home tab → D4 Diagnostics → D5 Energy+HVAC → D6 Presence+Security+Safety → D7 Spaces+Zones+Rooms → D8 Polish

Revised critical path:
1. **Cycle A** runs alongside v4.6.11 — minimal added cost
2. **Cycle B** ships BEFORE D3 (Home + Energy + HVAC depend on its new sensors)
3. **Cycle C** ships BEFORE D4 (Diagnostics tab is heavily dependent on coordinator telemetry)
4. D3-D7 then proceed with all backing data in place

**Defer-able if necessary:**
- D3 Home tab can use STATIC PLACEHOLDERS for "decisions today" + "5/5 healthy coordinators" if Cycle C slips. Surfaces them as "—" with a comment that v5.1 wires real data.

## Conclusion

P6's design is mostly grounded — 40 of ~60 values map to live sensors. The 10 attribute adds + 6 new sensor families are tractable in 3-4 short Python cycles totaling ~12-15h of work. The biggest concentration of new work is the per-coordinator telemetry set, which is its own valuable infrastructure layer independent of the dashboard.
