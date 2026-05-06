# Anomaly Detection & Alerting Survey — URA Codebase

**Survey Date:** May 5, 2026  
**Scope:** Complete inventory of anomaly detection, alerting, and recovery mechanisms across all coordinators  
**Motivation:** Before designing v4.5.0 B7 (regime change detection), understand existing infrastructure to avoid parallel systems and maximize reuse  
**Context:** B7 (Jensen-Shannon divergence on routine distributions) should leverage existing `AnomalyDetector` infrastructure rather than create new tables/pipelines.

---

## 1. Inventory of Anomaly Touchpoints

### 1.1 `AnomalyDetector` Class (Coordinator Diagnostics)

| Aspect | Details |
|--------|---------|
| **File:Line** | `domain_coordinators/coordinator_diagnostics.py:631–927` |
| **Class** | `AnomalyDetector` |
| **Severity Enum** | `AnomalySeverity` (line 42): `NOMINAL`, `ADVISORY` (z ≥2), `ALERT` (z ≥3), `CRITICAL` (z ≥4) |
| **What It Detects** | Point-in-time anomalies via z-score against learned `MetricBaseline` (Welford's online algorithm) |
| **Triggers** | `record_observation(metric_name, scope, value)` — computes z-score, classifies severity |
| **Persistence** | `store_anomaly()` → `anomaly_log` DB table (coordinator_diagnostics.py:797) |
| **Output Channels** | DB (`anomaly_log` table), in-memory `_active_anomalies` list (max 50), log (ERROR on store failure) |
| **Recovery Semantics** | Anomalies auto-clear from `_active_anomalies` when `clear_active_anomalies()` called or on coordinator teardown. DB row remains (resolved=0) until manually deleted via cleanup. No auto-expiry. |
| **Query Methods** | `get_anomaly_count(days)` — count in recent period; `get_status_summary()` — metrics + learning status; `load_baselines()` / `save_baselines()` — persistence |
| **Consumers** | HVAC, Security, Energy, Presence coordinators (instantiate and call `record_observation`) |
| **Notes** | Designed for real-time detection; stateless across coordinator restarts (baselines loaded from DB). No time-windowed aggregation—each observation scored independently. |

### 1.2 `anomaly_log` Database Table

| Aspect | Details |
|--------|---------|
| **File:Line** | `database.py:666–691` |
| **Schema** | `id (PK)`, `timestamp (TEXT)`, `coordinator_id`, `scope`, `metric_name`, `observed_value`, `expected_mean`, `expected_std`, `z_score`, `severity`, `sample_size`, `house_state`, `context_json`, `resolved (BOOL)`, `resolution_notes` |
| **Writers** | `AnomalyDetector.store_anomaly()` (coordinator_diagnostics.py:797) — called manually by coordinators after `record_observation()` flags anomaly |
| **Readers** | `AnomalyDetector.get_anomaly_count(days)` (coordinator_diagnostics.py:835), sensors (e.g., EnergyCircuitAnomalySensor indirectly), no direct dashboard query today |
| **Indexes** | `idx_anomaly_timestamp`, `idx_anomaly_coordinator`, `idx_anomaly_scope`, `idx_anomaly_severity` |
| **Retention** | No scheduled cleanup visible in code (no `cleanup_anomaly_log` method found); table grows indefinitely until manual prune or schema migration |
| **Notes** | Supports filtering by coordinator/scope/severity for future unified query. Storage is dense (one row per event, not aggregated). |

### 1.3 HVAC Coordinator Anomaly Detection

| Aspect | Details |
|--------|---------|
| **File:Line** | `domain_coordinators/hvac.py:447–459, 449–454` |
| **Anomaly Detector** | Instantiated with `HVAC_METRICS` (zone temp, humidity, fan runtime) and `minimum_samples=HVAC_ANOMALY_MIN_SAMPLES` (see hvac_const.py for exact value) |
| **Detection Trigger** | Every HVAC decision cycle (~5 min), metrics fed via `anomaly_detector.record_observation()` |
| **Severity Mapping** | Z-score → `AnomalySeverity` enum; used in decision context (line 849) |
| **Persistence** | Baselines auto-loaded on coordinator setup (line 456); saved periodically (assumed via coordinator teardown, not explicit nightly schedule found) |
| **Output** | In-memory anomaly list; async decision logs if `_decision_logger` present; DB anomaly_log via explicit `store_anomaly()` calls (not found in visible HVAC code—likely occurs in higher-order decision flow) |
| **Recovery** | Baselines fade older observations via `max_samples` cap in `MetricBaseline.update()` (coordinator_diagnostics.py:147–177) |
| **Notes** | v3.13.2+ infrastructure per comment on line 387. Anomalies inform decision urgency/confidence but don't directly trigger responses. |

### 1.4 Energy Coordinator Cross-Check Anomaly (`_envoy_data_anomaly_at`)

| Aspect | Details |
|--------|---------|
| **File:Line** | `domain_coordinators/energy.py:371–376, 1344–1364` |
| **What It Detects** | Envoy consumption cross-check divergence: `|Envoy_today_kwh - our_lifetime_delta_kwh| / reference * 100 > 15%` → possible Envoy reboot or stale snapshot |
| **Trigger** | Hourly cross-check in `_check_consumption_crosscheck()` (energy.py:1344) |
| **Severity** | Implicit `warning` (log level); no structured severity enum |
| **Detected At** | Line 1355: `self._envoy_data_anomaly_at = dt_util.now().isoformat()` (timestamp string) |
| **Output Channels** | In-memory flag (`_envoy_data_anomaly_at` string); consumed by `EnvoyStatusSensor` (sensor.py, implicit attribute) to flip from "online" to "stale" |
| **Recovery Semantics** | Auto-clears on next cross-check if divergence <5% (line 1356–1364). Sticky duration = 1 hour (until next hourly check). No DB persistence. |
| **Notes** | v4.3.0 D6 design; different from point-in-time anomalies—measures consistency of two data sources, not surprise vs. baseline. |

### 1.5 Energy Circuit Anomaly Detection & Sensor

| Aspect | Details |
|--------|---------|
| **File:Line** | `domain_coordinators/energy_circuits.py` (implementation presumed), `sensor.py:5623–5665` (sensor entity) |
| **Sensor Class** | `EnergyCircuitAnomalySensor` (sensor.py:5623) |
| **Entity** | `sensor.ura_circuit_anomaly` — state = "alert (N)" or "normal" |
| **What It Detects** | Per-circuit anomalies (tripped breaker, unusual consumption). Sourced from `energy.circuit_status` dict |
| **Attributes** | Full `circuit_status` dict (power, z_score, baseline_mean, panel, zero_duration_seconds per circuit) |
| **Output Channels** | Sensor state + attributes; NM notifications triggered for severe anomalies (energy.py:1943–1970, notify on "tripped_breaker" or "unusual_consumption") |
| **Severity Mapping** | NM severity derived from anomaly type and z_score magnitude (energy.py:1968–1970 sets hazard_type="circuit_anomaly", severity contextual) |
| **Recovery** | Anomalies auto-clear when circuit returns to normal (assumed on next energy polling cycle). No explicit cleanup. |
| **Notes** | Circuit anomalies map to safety hazards via `SIGNAL_SAFETY_HAZARD` dispatch (energy.py:478). Coupled to NM for notifications. |

### 1.6 Person Coordinator Transition Anomalies

| Aspect | Details |
|--------|---------|
| **File:Line** | `domain_coordinators/presence.py:376–440, 1514–1616` |
| **What It Detects** | Invalid state transitions (e.g., ARRIVING→SLEEP), occupancy mismatches (motion in away room) |
| **Trigger** | State machine validation in `_run_state_inference()` (presence.py:1397) and periodic inference (presence.py:1310) |
| **Severity** | Implicit (no structured severity); transitions either accepted or rejected by FSM, rejected = implicit warning-level anomaly |
| **Detection** | Transition validation (presence.py:1397) returns boolean; on failure, transition deferred with hysteresis-blocked retry (presence.py:1500–505) |
| **Output Channels** | Activity logger via `activity_logger.log()` on successful transition (presence.py:1458–1462); decision_log via `_log_state_transition()` (presence.py:1638–1644, logs to DB) |
| **Recovery Semantics** | Invalid transitions deferred, retried after hysteresis timer expires. No persistent anomaly row—failure is ephemeral, success moves to next inference cycle. |
| **Accuracy Tracking** | `_log_transition_outcome()` (presence.py:1596–1616) records if prior transition was contradicted (e.g., just arrived, now away again <1 min). Writes to prediction_results table (assumed via database.save_prediction_result). |
| **Notes** | Anomalies = contradictions between prediction and reality, tracked for Bayesian accuracy (v3.15.0+). No AnomalyDetector integration; independent FSM-based. |

### 1.7 Bayesian Predictor Anomaly Score

| Aspect | Details |
|--------|---------|
| **File:Line** | `bayesian_predictor.py:774–822` |
| **Method** | `get_anomaly_score(room_id, is_occupied)` |
| **What It Detects** | Room unexpectedly occupied when Bayesian prediction < 10% and learning_status=ACTIVE |
| **Trigger** | Called from binary sensor logic (binary_sensor.py:1691) on occupancy change |
| **Severity** | No severity enum; returns boolean `anomaly` field (true/false) |
| **Output Channels** | Binary sensor (`sensor.ura_<room>_occupancy_anomaly`, state = "on"/"off") + attributes (predicted_prob, learning_status, time_bin, day_type) |
| **Recovery** | Anomaly clears when occupancy returns to false OR predicted_prob rises above threshold. No DB persistence, stateless per sensor read. |
| **Notes** | Point-in-time detection; no persistence mechanism. Different use case than AnomalyDetector—Bayesian is prediction-validation focused. |

### 1.8 Safety Coordinator Hazard Detection

| Aspect | Details |
|--------|---------|
| **File:Line** | `domain_coordinators/safety.py:79–145, 1159–1280` |
| **Hazard Types** | `HazardType` enum (safety.py:79): CARBON_MONOXIDE, HIGH_CO2, HIGH_TVOC, FREEZE_RISK, OVERHEAT, WATER_LEAK, SMOKE, HVAC_FAILURE, FLOODING, CIRCUIT_ANOMALY |
| **Detection Methods** | Sensor thresholds (co ppm, co2 ppm, tvoc ppb, temp rise/fall); binary sensor triggers (leak, smoke); circuit anomaly from energy |
| **Severity Classification** | Implicit mapping (safety.py:124–145 defines response thresholds, not severity enums); mapped to NM severity on dispatch |
| **Triggers** | Periodic coordinator update cycle; cross-coordinator signal handlers (SIGNAL_SAFETY_HAZARD dispatch, safety.py:577–1190) |
| **Output Channels** | `SIGNAL_SAFETY_HAZARD` signal (async_dispatcher_send, safety.py:1190) → cross-coordinator handlers (HVAC, energy, music, security); NM notifications (async_notify, safety.py:1311–1313); activity logger |
| **Payload Structure** | `SafetyHazard` dataclass (signals.py, fields: hazard_type, severity, location, value, timestamp) |
| **Recovery** | Hazards clear when sensor returns to safe threshold. No persistent anomaly row. Transient signal-based architecture. |
| **Notes** | Safety hazards are critical-path—trigger HVAC emergency actions (fan boost, freeze protection, CO fan stop). Extensively cross-linked to HVAC/NM via signal handlers (HVAC hazard response, safety.py:878–931). |

### 1.9 Notification Manager Alert Wrapping

| Aspect | Details |
|--------|---------|
| **File:Line** | `domain_coordinators/notification_manager.py:613–640 (async_notify), 1311, 2062` |
| **Method** | `async_notify(severity, title, message, ...)` |
| **Severity Vocab** | "info", "warning", "alert", "critical" (maps to HA severity levels) |
| **Storage** | `notification_log` table (database.py:761–781): `id, timestamp, coordinator_id, severity, title, message, hazard_type, location, person_id, channel, delivered, acknowledged, ack_time, cooldown_expires` |
| **Filtering** | Severity threshold (user config), quiet hours (time-based), kill switch (observation mode), cooldown per alert type (optional) |
| **Output** | SMS/email/push via configured channels; also HA persistent notifications |
| **Recovery** | Alerts don't auto-clear; marked acknowledged by user. Cooldown prevents re-alert for same event within window (e.g., 30d for regime shifts in B7 plan). |
| **Notes** | NM is the **alerting surface** for all coordinators. All critical anomalies should flow through NM.async_notify(). Activity logger feeds NM. |

### 1.10 Activity Logger

| Aspect | Details |
|--------|---------|
| **File:Line** | `activity_logger.py:37–167` |
| **Purpose** | Log all coordinator decisions and automation actions with dedup to avoid spam |
| **Storage** | `ura_activity_log` table (presumed in database.py, not yet visible in schema grep); also fires `ura_action` HA events |
| **Importance Levels** | "info" (30s dedup), "notable" (60s dedup), "critical" (300s dedup) |
| **Output Channels** | DB, HA events, `SIGNAL_ACTIVITY_LOGGED` signal dispatch (activity_logger.py:120) |
| **Consumers** | Sensors subscribe to signal for activity counters (sensor.py:8669 references). Decision/action tracing for diagnostics. |
| **No Anomaly Classification** | Activity log is event-centric, not anomaly-centric. Records "what happened", not "was this anomalous". |
| **Notes** | v4.0.11+; complements anomaly_log by providing human-readable action timeline. |

### 1.11 Repair Issues (`ir.async_create_issue`)

| Aspect | Details |
|--------|---------|
| **File:Line** | `__init__.py:1423–1436 (Energy Envoy validation failure)` |
| **Condition Triggering** | Energy Envoy entity validation fails (missing, invalid, timeout) during setup |
| **Issue ID** | `energy_envoy_invalid_{entry_id}` |
| **Severity** | `IssueSeverity.ERROR` (non-fixable, requires user intervention) |
| **Recovery** | Issue auto-deleted if validation passes on next reload (`__init__.py:1449–1458`) |
| **Output** | HA Settings > System > Repairs UI; appears until user fixes config |
| **Notes** | Single known repair issue in current codebase. B7 plan does not propose new repair issues (uses NM for notifications). |

### 1.12 Transit Validator (Occupancy Prediction Validation)

| Aspect | Details |
|--------|---------|
| **File:Line** | `sensor.py:2459–2461` (usage); transit_validator module presumed in codebase |
| **Purpose** | Validate occupancy transitions against camera sightings (geofence vs. vision) |
| **Method** | `get_last_camera_sighting(person_id)` — cross-checks person's presence claim against last Frigate sighting |
| **Anomaly Flagged** | Mismatch between geofence state and camera data (e.g., geofence says home, camera hasn't seen person in 2h) |
| **Output** | Implicit (consulted during sensor attribute calculation, not persisted as anomaly row) |
| **Recovery** | Stateless; re-evaluated every sensor update cycle |
| **Notes** | Quality Context note (BACKLOG.md): Frigate face DB undersized (11–17 samples at 0.9 threshold). Low match rate = high false-negative risk. Transit validator mitigates via geofence fallback. |

---

## 2. Severity / Vocabulary Inconsistency Map

### Cross-Tabulation: Which Touchpoints Use Which Severity Terms

| Touchpoint | Severity Enum / Terms Used | Mapped Value | Notes |
|------------|----|---|---|
| **AnomalyDetector** | `AnomalySeverity`: NOMINAL, ADVISORY, ALERT, CRITICAL | Z-score thresholds (2.0, 3.0, 4.0) | Structured, numeric mapping |
| **Envoy Cross-Check** | Implicit (log WARNING) | No enum; severity = "warning" (informal) | Unstructured |
| **Circuit Anomaly** | Implicit (hazard_type in NM payload) | Derived contextually in energy.py:1968–1970 | Depends on anomaly type |
| **Person Transitions** | Implicit (FSM validation) | No severity; binary (valid/invalid) | Unstructured |
| **Bayesian Anomaly Score** | Boolean (anomaly true/false) | No severity; implicit "warning" | Unstructured |
| **Safety Hazards** | Implicit (HazardType, RESPONSE_SEVERITY) | Maps to NM severity on dispatch | Contextual per hazard type |
| **Notification Manager** | "info", "warning", "alert", "critical" | User-configurable threshold | HA-standard vocabulary |
| **Activity Logger** | "info", "notable", "critical" | Dedup window only; not severity | Importance-based, not risk-based |
| **Repair Issues** | `IssueSeverity.ERROR` | Single level | HA standard |

### Vocabulary Inconsistencies

| Issue | Example | Impact |
|-------|---------|--------|
| **Multiple severity scales** | AnomalySeverity (4 levels, z-score driven) vs. NM (4 levels, user-driven) vs. ActivityLogger (3 levels, dedup-driven) | Dashboard queries can't unify. Sensor attributes use different enums. |
| **Implicit vs. explicit** | Envoy divergence = implicit "warning", no enum | Hard to query/filter. Risk of miscommunication. |
| **Hazard type vs. severity** | Safety coordinator conflates hazard_type with severity | Circuit anomaly could be low/high impact; no way to distinguish. |
| **Boolean anomalies** | Bayesian occupancy anomaly = true/false, no magnitude | Cannot rank by risk; binary sensor only. |

### Proposed Unified Vocabulary

**For v4.5.0 onwards**, adopt **single severity scale** across all coordinators:

```python
class AnomalySeverity(StrEnum):
    INFO = "info"          # Noteworthy but normal
    WARNING = "warning"    # Unexpected; requires attention
    CRITICAL = "critical"  # Emergency; immediate action required
```

Map existing values:
- `AnomalyDetector.NOMINAL` → `AnomalySeverity.INFO`
- `AnomalyDetector.ADVISORY` → `AnomalySeverity.WARNING`
- `AnomalyDetector.ALERT` / `CRITICAL` → `AnomalySeverity.CRITICAL`
- All FSM/hazard events → one of above based on context
- B7 regime shifts: `INFO` (drifting) / `WARNING` (shifted) / `CRITICAL` (major shift)

---

## 3. Output Channel Inconsistency Map

### Cross-Tabulation: Which Touchpoints Emit Via Which Channels

| Touchpoint | Sensor State | Sensor Attr | Log | DB Row | Signal | Repair Issue | NM Notify |
|------------|----|---|---|---|---|---|---|
| **AnomalyDetector** | — | — | ERROR (store fail) | ✓ anomaly_log | — | — | — (coordinators decide) |
| **Envoy Cross-Check** | — | ✓ (EnvoyStatusSensor.stale) | ✓ WARNING | — | — | — | — |
| **Circuit Anomaly Sensor** | ✓ (alert/normal) | ✓ (details) | — | — | — | — | ✓ (NM.async_notify) |
| **Person Transitions** | ✓ (house_state) | ✓ (transition count) | ✓ INFO | ✓ (decision_log, prediction_results) | — | — | — |
| **Bayesian Anomaly** | ✓ (anomaly on/off) | ✓ (predicted, learning_status) | — | — | — | — | — |
| **Safety Hazards** | — | — | — | — | ✓ SIGNAL_SAFETY_HAZARD | — | ✓ (NM.async_notify) |
| **NM Alerts** | — | — | — | ✓ notification_log | — | — | ✓ (primary output) |
| **Activity Logger** | — | — | — | ✓ ura_activity_log | ✓ SIGNAL_ACTIVITY_LOGGED | — | — |

### Data Loss & Duplication Issues

| Issue | Touchpoint | Impact |
|-------|-----------|--------|
| **Only logged, not queryable** | Envoy divergence = log WARNING, no anomaly_log row | No historical query ("show all divergences in last 7 days") |
| **Double-emission** | Circuit anomaly → NM notify + anomaly_log (via coordinator) | Risk of duplicate notifications; inconsistent timing |
| **No sensor fallback** | AnomalyDetector baselines in memory only until coordinator teardown | Baselines lost on crash; restart reads from DB but in-flight anomalies are lost |
| **Transient signals** | Safety hazards via `SIGNAL_SAFETY_HAZARD` only; no sensor surface | User can't query "show all hazards in last 24h"; transient = can miss on code reload |
| **Missing aggregation** | Each anomaly written individually to DB; no grouped view | Queries for "anomaly_count by coordinator" require aggregation in code, not DB |

### Recommended: Unified Emission Pattern

All anomalies should emit via **at least two channels**:

1. **DB (always)** → `anomaly_log` (or future `anomaly_events` table)
2. **Signal (for real-time)** → `SIGNAL_ANOMALY_DETECTED` (new, for coordinators to respond)
3. **NM (optionally)** → for user-facing notifications (depends on severity + config)
4. **Sensor (optionally)** → for dashboard display (derived from DB, cached query)

---

## 4. Recovery Semantics Map

### Auto-Clear Behavior by Touchpoint

| Touchpoint | Auto-Clear Condition | Clear Timing | Orphaned Risk |
|-----------|---|---|---|
| **AnomalyDetector** | `clear_active_anomalies()` called explicitly OR coordinator teardown | On demand | ✓ HIGH: DB rows never auto-delete; `resolved=0` forever unless manually pruned |
| **Envoy Cross-Check** | Divergence <5% on next hourly check | ~1h window | — (in-memory flag clears automatically) |
| **Circuit Anomaly** | Circuit power returns to normal | Next polling cycle (~5 min) | — |
| **Person Transition** | FSM accepts transition on retry, or hysteresis timer expires | Deferred retry (tunable backoff) | — (ephemeral validation, no DB persistence) |
| **Bayesian Anomaly** | Occupancy changes OR predicted_prob rises >10% | Next sensor update (5–60s default) | — (ephemeral, sensor-driven) |
| **Safety Hazards** | Sensor threshold returns to safe range | Immediate (event-driven) | — (no DB persistence; transient via signal) |
| **NM Alerts** | User acknowledges OR cooldown expires | On user action or time | ✓ MEDIUM: Acknowledged flag set, but row remains in DB |
| **Activity Log** | Dedup cache expires after max(dedup_windows) * 2 | Opportunistic (on next log call) | — (cache-only, not DB) |

### Orphaned State Risk Analysis

| Risk Level | Touchpoint | Reason | Mitigation |
|-----------|-----------|--------|---|
| **HIGH** | AnomalyDetector / anomaly_log | No scheduled cleanup; rows accumulate indefinitely | Add `cleanup_anomaly_log(retention_days)` to nightly maintenance (Bug Class #27 pattern) |
| **MEDIUM** | NM notifications | `acknowledged=1` but row persists | Add retention policy (e.g., 90 days post-ack) to nightly cleanup |
| **LOW** | In-memory lists (active anomalies) | Capped at 50 rows; old entries cycled out | No risk if coordinator lifecycle is clean (Bug Class #19 concern) |

### Persistence vs. Transience

| Characteristic | AnomalyDetector | Safety Hazard | Bayesian Anomaly | Person Transition |
|---|---|---|---|---|
| **Persisted?** | Yes (anomaly_log) | No (signal only) | No (sensor attr only) | Partial (decision_log, prediction_results) |
| **Stateful Across Restart?** | Yes (baselines from DB) | No | No | Yes (decision records queryable) |
| **Real-Time Response?** | Indirect (coordinators poll results) | Direct (signal handlers) | Direct (binary sensor) | Direct (FSM logic) |

---

## 5. Schema Gaps

### Query Scenarios Today

| Query | How It Works Today | Gap |
|-------|---|---|
| "Show anomalies in last 24h" | `AnomalyDetector.get_anomaly_count(days=1)` (code-level) or raw SQL on `anomaly_log` | No built-in sensor; requires direct DB access |
| "Show anomalies by coordinator" | Coordinator filters via WHERE clause; no aggregation helper | Must GROUP BY in code or SQL |
| "Show severity distribution" | Manual: GROUP BY severity on `anomaly_log` | No summary sensor |
| "Show hazards in last 7d" | No query exists (safety hazards not persisted) | Data completely lost post-restart |
| "Show resolved vs. unresolved" | WHERE resolved=0 or 1; but who sets resolved=1? | No resolver logic in codebase; likely orphaned |
| "Show activity timeline" | `ura_activity_log` table (assumed) with activity_logger.log() writes | Activity log exists but not tied to anomalies; separate schema |

### Schema Limitations

| Limitation | Impact | Fix |
|-----------|--------|-----|
| **No anomaly_type column** | Cannot distinguish point-in-time vs. regime-shift vs. hazard-based | v4.5.0 B7 adds discriminator (line 105, BACKLOG.md) |
| **No correlation_id** | Cannot link related anomalies across coordinators (e.g., circuit anomaly → energy coordinator → HVAC override hazard) | Add UUID column for multi-coordinator causality chains |
| **No acknowledged_at / resolution_at** | Cannot query "resolve time" or "time to acknowledgment" | Expand resolved (boolean) to resolution_at (datetime) + resolution_method (enum) |
| **No entity_id in anomaly_log** | Cannot link anomaly to HA entity; requires manual correlation | Add optional `entity_id` column |
| **No room_id / zone_id** | Cannot slice by location; anomalies are coordinator-global | Add optional `room_id`, `zone_id` for room/zone-scoped anomalies |
| **No person_id** | Person-scoped anomalies (occupancy, regime) cannot be filtered | Add optional `person_id` column |

---

## 6. Proposed Unified `AnomalyEvent` Shape

### Dataclass Definition

```python
@dataclass
class AnomalyEvent:
    """Unified anomaly representation for all coordinators.
    
    Replaces per-coordinator ad-hoc state tracking with a single, queryable schema.
    Subsumes both point-in-time detection (existing) and regime shifts (B7).
    """
    
    # Required: Core identity
    id: Optional[int] = None  # DB auto-increment
    timestamp: datetime = field(default_factory=dt_util.utcnow)  # UTC ISO
    coordinator: str  # "energy", "hvac", "person", "safety", "security", etc.
    type: str  # Discriminator: "point_in_time" | "regime_shift" | "hazard" | "transition"
    event_name: str  # Namespace: "energy.circuit_overcurrent", "person.occupancy_anomaly", "hvac.zone_temp_extreme", etc.
    severity: str  # "info" | "warning" | "critical" (unified vocab)
    
    # Context: What + where
    observed_value: Optional[float] = None  # Actual measurement (anomaly point-in-time)
    expected_value: Optional[float] = None  # Baseline / predicted value
    metric_name: Optional[str] = None  # "circuit_power", "zone_temperature", "occupancy_probability", etc.
    z_score: Optional[float] = None  # Z-score if applicable
    
    # Location: Optional spatial context
    entity_id: Optional[str] = None  # HA entity (e.g., "climate.zone_1_thermostat")
    room_id: Optional[str] = None  # Room/zone ID (e.g., "zone_1", "room_master_bedroom")
    location_name: Optional[str] = None  # Human-readable (e.g., "Master Bedroom")
    
    # Person: Optional person context
    person_id: Optional[str] = None  # Person entity (e.g., "person.john")
    
    # Temporal state: Before, during, after
    detected_at: datetime = field(default_factory=dt_util.utcnow)  # When anomaly first detected
    recovery_at: Optional[datetime] = None  # When anomaly resolved (set on clear)
    acknowledged_at: Optional[datetime] = None  # When user acknowledged (if applicable)
    
    # Payload: Type-specific details (JSON)
    payload: Dict[str, Any] = field(default_factory=dict)
    # Examples:
    #   point_in_time: {"sample_size": 50, "baseline_mean": 72.1, "baseline_std": 1.5}
    #   regime_shift: {"js_divergence": 0.65, "recent_window": 14, "ref_window": 90, "top_room_change": {"from": "bedroom", "to": "kitchen"}}
    #   hazard: {"hazard_type": "overheat", "threshold": 80, "measured": 84}
    #   transition: {"old_state": "AWAY", "new_state": "HOME", "confidence": 0.95}
    
    # Deduplication + correlation
    correlation_id: Optional[str] = None  # UUID linking related anomalies (e.g., circuit → energy → HVAC)
    
    # Recovery tracking
    auto_clear: bool = True  # If True, anomaly clears when condition resolves; if False, requires manual ack
    is_resolved: bool = False  # Current resolution state
    resolution_method: Optional[str] = None  # "auto_clear" | "user_acknowledge" | "system_reset" | "timeout_expired"
    
    # Metadata
    house_state: Optional[str] = None  # House state at detection time (HOME_DAY, SLEEPING, AWAY, etc.)
    context: Dict[str, Any] = field(default_factory=dict)  # Coordinator-specific debug context

    @property
    def age_seconds(self) -> float:
        """Time since detection."""
        return (dt_util.utcnow() - self.detected_at).total_seconds()

    @property
    def resolved_in_seconds(self) -> Optional[float]:
        """Time from detection to resolution."""
        if self.recovery_at:
            return (self.recovery_at - self.detected_at).total_seconds()
        return None
```

### Database Table Mapping

```sql
CREATE TABLE anomaly_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,  -- UTC ISO
    coordinator TEXT NOT NULL,
    type TEXT NOT NULL,  -- point_in_time, regime_shift, hazard, transition
    event_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    
    -- Metric context
    observed_value REAL,
    expected_value REAL,
    metric_name TEXT,
    z_score REAL,
    
    -- Location
    entity_id TEXT,
    room_id TEXT,
    location_name TEXT,
    
    -- Person
    person_id TEXT,
    
    -- Temporal
    detected_at TEXT NOT NULL,
    recovery_at TEXT,
    acknowledged_at TEXT,
    
    -- Payload
    payload_json TEXT NOT NULL,  -- {"...": "..."}
    
    -- Correlation
    correlation_id TEXT,
    
    -- Recovery
    auto_clear BOOLEAN DEFAULT 1,
    is_resolved BOOLEAN DEFAULT 0,
    resolution_method TEXT,
    
    -- Metadata
    house_state TEXT,
    context_json TEXT
);

-- Indexes for common queries
CREATE INDEX idx_anomaly_events_timestamp ON anomaly_events(timestamp);
CREATE INDEX idx_anomaly_events_coordinator ON anomaly_events(coordinator);
CREATE INDEX idx_anomaly_events_type ON anomaly_events(type);
CREATE INDEX idx_anomaly_events_severity ON anomaly_events(severity);
CREATE INDEX idx_anomaly_events_room_id ON anomaly_events(room_id);
CREATE INDEX idx_anomaly_events_person_id ON anomaly_events(person_id);
CREATE INDEX idx_anomaly_events_resolved ON anomaly_events(is_resolved);
CREATE INDEX idx_anomaly_events_correlation ON anomaly_events(correlation_id);
```

### Migration Path

| Existing Touchpoint | Maps To `AnomalyEvent` | Payload Structure |
|---|---|---|
| **AnomalyDetector** | type=`point_in_time`, event_name=`<coordinator>.<metric>` | `{sample_size, baseline_mean, baseline_std, baseline_variance}` |
| **Envoy Cross-Check** | type=`point_in_time`, event_name=`energy.consumption_crosscheck_divergence` | `{envoy_kwh, our_kwh, divergence_pct, reference}` |
| **Circuit Anomaly** | type=`point_in_time`, event_name=`energy.circuit_anomaly` | `{circuit_id, power_w, z_score, baseline_w, zero_duration_s}` |
| **Person Transition** | type=`transition`, event_name=`person.state_transition` | `{old_state, new_state, confidence, hysteresis_blocked}` |
| **Bayesian Anomaly** | type=`point_in_time`, event_name=`person.occupancy_anomaly` | `{predicted_prob, time_bin, day_type}` |
| **Safety Hazard** | type=`hazard`, event_name=`safety.<hazard_type>` | `{hazard_type, threshold, measured_value, location}` |
| **B7 Regime Shift** | type=`regime_shift`, event_name=`person.routine_change` | `{js_divergence, recent_window_days, ref_window_days, top_room_changes}` |

### Backward Compatibility

Existing `anomaly_log` table:
- Preserved as-is; migrated rows have type=`point_in_time`, mapped event_name
- New code writes to `anomaly_events` (or renames `anomaly_log` → `anomaly_events` in single migration)
- Queries updated to use new table; cleanup policies adjusted (add `recovered_at` auto-delete)

---

## 7. Reuse Opportunities for B7 (Regime Change Detection)

### What B7 Actually Needs

**B7 Spec** (BACKLOG.md:79–112):
- Nightly batch: compute JS divergence on room-frequency distributions for each (person, time_bin, day_type) cell
- Recent window (14d) vs. reference window (90d)
- Threshold: `JS < 0.3` = stable, `0.3–0.5` = drifting, `>0.5` = shifted
- Persistence: require N consecutive nightly checks before flagging (suppress vacation false positives)
- Surface: per-person sensor `routine_status` (stable/drifting/shifted) + house aggregate

### Proposed Leverage of Existing Infrastructure

| Component | Leverage | How |
|-----------|----------|-----|
| **AnomalyDetector** | Reuse persistence layer | B7 creates anomaly_events rows (type=`regime_shift`) instead of new table. Coordinator-level batch job queries `person_visits`, computes JS, writes events. |
| **AnomalySeverity** | Reuse severity vocab | JS magnitude → AnomalySeverity: `0.3–0.5` = INFO (drifting), `0.5–0.7` = WARNING (shifted), `>0.7` = CRITICAL (major shift). **Solves vocab inconsistency** (sec 2). |
| **Database write queue** | Reuse async persistence | B7 calls `anomaly_detector.store_anomaly()` or direct `anomaly_events` insert via DB write queue (no new queue). |
| **NM notifications** | Reuse alerting surface | B7 anomaly_events trigger NM via signal handler (similar to safety hazards). Severity + user config determine if user is notified. |
| **Activity logger** | Reuse action tracking | Nightly batch logs "Routine analysis completed" event; regime shifts logged as "Routine pattern shift detected for <person>". |
| **Sensor surface** | Reuse from anomaly_events query | Per-person sensor queries `anomaly_events WHERE type='regime_shift' AND person_id=? AND is_resolved=0 ORDER BY timestamp DESC LIMIT 1`. |
| **Deduplication** | Reuse activity_logger logic | Prevent duplicate NM alerts if the same (person, cell) shifts twice in one night: check NM notification_log cooldown (30d per BACKLOG.md). |

### What B7 Cannot Reuse (Genuinely New)

| Need | Reason | Scope |
|------|--------|-------|
| **JS divergence math** | No existing KL/JS implementation in codebase | ~150 lines: compute_js_divergence(), compute_kl_divergence() in regime_detector.py |
| **Persistence guard** | Persistence counter (N consecutive checks before flag) | ~30 lines: in-memory counter dict, incremented nightly, cleared on recovery |
| **Cell staleness check** | "Has this cell seen recent observations?" for "away_typical" (B6 + B7 shared) | ~20 lines: helper query on person_visits |
| **Nightly batch scheduler** | Coordinator-level periodic task (runs at 2:30 AM) | ~30 lines: async task registration in Presence coordinator |
| **Regime detector coordinator** | Could be standalone or embedded in Presence | ~200 lines if standalone, ~100 if embedded + reusing Presence's nightly infrastructure |

### Recommended B7 Architecture

**Avoid creating parallel infrastructure.** Instead:

1. **Extend `AnomalyEvent`** schema (sec 6) with `type='regime_shift'` discriminator (v4.5.0 D0, before B6/B7)
2. **Add `regime_detector.py`** module (~250 lines production)
   - `detect_regime_shift(person_id, time_bin, day_type, hass)` → returns `AnomalyEvent` with JS divergence payload
   - Reuse `AnomalyDetector` for... nothing directly (JS is different math); but write output to shared `anomaly_events` table
3. **Register nightly batch** in Presence coordinator (or new DetectionBatch coordinator)
   - Query `person_visits` for (person, time_bin, day_type) cells
   - Call regime_detector for each → collect AnomalyEvents
   - Write events to DB via anomaly_detector.store_anomaly() or direct insert
   - Increment persistence counters; flag when threshold reached
4. **Create sensors** querying `anomaly_events` with type filters
5. **NM integration** via signal dispatch (analogous to safety hazards)

### Cost Reduction

**Original plan** (BACKLOG.md line 159–170):
- 640 production lines (regime_detector, schema migration, sensors, integration, config flow, notifications, indexes)

**With reuse:**
- regime_detector.py: 250 lines
- Schema migration (add `type` column, index): 20 lines
- Sensor classes (query anomaly_events): 120 lines (vs. 140 in isolated design)
- Coordinator integration: 50 lines (reuse async_notify, signal dispatch patterns)
- Config flow: 70 lines (unchanged)
- NM hook: 30 lines (unchanged)
- **Total: ~540 lines** (save ~100 lines by not duplicating persistence, notifications, recovery logic)
- **Test cost reduced** (~80 lines for regime detector tests, vs. ~410 if all infrastructure duplicated)

**Net benefit:** Unified schema + shared recovery semantics mean future anomaly features (v4.6+) plug into same infrastructure.

---

## 8. Recommendations for v4.5.0 Plan

### Recommendation #1: Adopt Unified AnomalyEvent Schema Before B6/B7

**Rationale:**
- Current codebase has 7+ ad-hoc anomaly storage mechanisms (AnomalyDetector, Envoy flag, circuit sensor state, FSM validation, Bayesian binary sensor, safety signals, activity log)
- BACKLOG.md lists B6 and B7 together for a reason: both are about behavior change detection and need identical schema
- Duct-taping regime detection onto AnomalyDetector (different math, different time scale) will create confusion

**Action:**
- **v4.5.0 D0 (parallel with B3 planning):** Finalize `AnomalyEvent` dataclass + DB schema migration
- Create `anomaly_events` table; migrate existing `anomaly_log` rows (type=`point_in_time`)
- Add discriminator column; index on (type, coordinator, person_id, is_resolved)
- **Risk:** Medium (schema change, migration). **Mitigated by:** Backward compatibility layer (reads both tables briefly), comprehensive test suite
- **ROI:** High. B7 ships in 540 instead of 640 lines; future anomaly features reuse immediately.

### Recommendation #2: Unify Severity Vocabulary Across All Coordinators

**Rationale:**
- Table 2 shows 8 different severity naming schemes (nominal/advisory/alert/critical, info/warning/error, boolean, implicit)
- Makes sensors inconsistent; makes queries impossible
- NM is the de facto severity scale; align others to it

**Action:**
- **v4.5.0 D1:** Replace all coordinator-specific severity enums with centralized `AnomalySeverity` enum: `INFO | WARNING | CRITICAL`
- Map legacy severities:
  - `AnomalyDetector.NOMINAL` → `INFO`
  - `AnomalyDetector.ADVISORY` → `WARNING`
  - `AnomalyDetector.ALERT | CRITICAL` → `CRITICAL`
  - Safety hazard responses → contextual (e.g., CO = CRITICAL, high CO2 = WARNING)
  - B7 regime JS: 0.3–0.5 → `WARNING`, >0.5 → `CRITICAL`
- Update NM.async_notify() signature to accept `AnomalySeverity` enum (preserve HA mapping internally)
- **Risk:** Low (internal refactor). **Mitigated by:** All enum values map 1:1 to existing thresholds.
- **ROI:** Medium. Unblocks unified queries. Simplifies sensor logic (no per-coordinator switch statements).

### Recommendation #3: Add Nightly Cleanup for Orphaned Anomalies (Bug Class #27 Prevention)

**Rationale:**
- Current code has no cleanup for `anomaly_log` (now `anomaly_events`)
- Table will grow unbounded; first cleanup (v4.2.8 pattern) will block write queue
- NM notifications also lack retention policy

**Action:**
- **v4.5.0 D2:** Add to nightly maintenance schedule (2:30 AM):
  ```python
  async def cleanup_anomaly_events(retention_days: int = 90):
      """Delete resolved anomalies older than retention_days."""
      cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
      async with db._db() as dbconn:
          # Batch delete (Bug Class #25 pattern)
          for i in range(1000):  # 1000 batches max
              cursor = await dbconn.execute("""
                  DELETE FROM anomaly_events 
                  WHERE is_resolved=1 AND recovery_at < ? 
                  LIMIT 500
              """, (cutoff,))
              if cursor.rowcount == 0:
                  break
              await asyncio.sleep(0.1)
  ```
- Similarly for `notification_log`: delete acknowledged alerts older than 90 days
- Document retention policy in config flow (user-tunable, default 90 days)
- **Risk:** Low (standard pattern, tested in v4.2.8). **Mitigated by:** Bounded batches, time budget.
- **ROI:** High. Prevents v4.2.8-class performance regression. Improves query performance (smaller tables).

### Recommendation #4: Establish AnomalyEvent as Canonical Cross-Coordinator Communication

**Rationale:**
- Current coordinators communicate via ad-hoc channels: signals (`SIGNAL_SAFETY_HAZARD`), NM notifications, activity logs
- B7 will require coordination between Presence detector and notification surface
- A unified AnomalyEvent schema enables:
  - Correlation (e.g., circuit anomaly → energy coordinator → trigger HVAC override)
  - Cross-coordinator filtering (e.g., "show all events linked to this person's routine shift")
  - Unified diagnostics dashboard

**Action:**
- **v4.5.0 D3:** Establish wire protocol:
  1. All coordinators emit anomalies to `anomaly_events` table (the "source of truth")
  2. Signals (`SIGNAL_ANOMALY_DETECTED`) fire for real-time handlers (HVAC, NM)
  3. NM listens to signals, queries `anomaly_events` for context before notifying user
  4. Activity log deduplicates alerts (prevent spam) using NM cooldown policy
- Document in README: "All anomalies flow through AnomalyEvent table. Signals are real-time; tables are queryable."
- Create example sensor: `sensor.ura_anomaly_count_24h` (queries anomaly_events for last 24h by severity)
- **Risk:** Medium (behavioral change; could expose existing anomaly spam if not filtered). **Mitigated by:** Phased rollout (B7 first, then migrate existing touchpoints).
- **ROI:** Very High. Unblocks future "anomaly dashboard" feature. Simplifies cross-coordinator testing.

---

## 9. Out of Scope (Explicit)

The following are **not addressed** by this survey and should be planned separately:

| Item | Why | Plan |
|------|-----|------|
| **Performance impact of unified schema** | Depends on query patterns; needs load testing with 1M+ rows | Defer to v4.5.1 optimization phase |
| **Cross-system anomaly correlation** | Requires policy language (e.g., "if circuit anomaly + HVAC override, suppress NM alert") | Future feature; out of v4.5.0 scope |
| **Anomaly ML models (ARIMA, PROPHET)** | Would replace Welford's algorithm; major refactor | Deferred; Welford's is sufficient for now |
| **Real-time anomaly streaming to external system** | Would require webhook/MQTT publisher | Out of scope (add after v4.5.0 stabilizes) |
| **Anomaly replay / forensics UI** | Dashboard to visualize anomalies over time | Future (v4.6.0 Optimization Coordinator feature) |
| **Automatic anomaly-driven self-correction** | Coordinator would auto-adjust its own thresholds based on false positive rates | Advanced; deferred |
| **Privacy-sensitive anomaly filtering** | E.g., don't log occupancy anomalies when guest mode active | Config flow feature; separate ticket |
| **Multi-tenant anomaly isolation** | Not applicable to single-household URA | N/A |

---

## Summary Table: Touchpoint Inventory

| Touchpoint | Type | File:Line | Severity Enum | Output Channels | Recovery | Persistent? | DB Table | Consumers |
|-----------|------|-----------|---|---|---|---|---|---|
| AnomalyDetector | Detector | coordinator_diagnostics.py:631 | AnomalySeverity | anomaly_log, log | On demand | Yes | anomaly_log | HVAC, Security, Energy |
| Envoy Cross-Check | Detector | energy.py:1344 | Implicit | Flag, sensor attr, log | Divergence <5% | No | — | EnvoyStatusSensor |
| Circuit Anomaly | Sensor | sensor.py:5623, energy_circuits.py | Contextual | Sensor state/attr, NM | Normal return | No | — | Dashboard, NM |
| Person Transition | Validator | presence.py:1367 | Implicit | Decision log, activity log, sensor | FSM accept | Partial | decision_log, prediction_results | Bayesian accuracy |
| Bayesian Anomaly | Detector | bayesian_predictor.py:774 | Boolean | Binary sensor | Occupancy/pred change | No | — | Dashboard |
| Safety Hazard | Event | safety.py:79 | Contextual | Signal, NM, activity log | Threshold recovery | No | — | HVAC, NM, Music Following |
| NM Alert | Alert | notification_manager.py:613 | NM standard | notification_log, NM channel | User ack / cooldown | Yes | notification_log | User |
| Activity Log | Logger | activity_logger.py:37 | Importance | ura_activity_log, signal, events | Dedup expiry | Yes | ura_activity_log | Sensor, logbook |
| Repair Issue | Alert | __init__.py:1423 | IssueSeverity | HA Repairs UI | Config fix | No | — | User |
| Transit Validator | Validator | sensor.py:2459, transit_validator | N/A | Implicit (attr) | Stateless | No | — | Occupancy sensor |

---

## Appendix: File Reference Index

**Coordinator Diagnostics:**
- `domain_coordinators/coordinator_diagnostics.py` — AnomalyDetector (631–927), DecisionLogger (206–325), ComplianceTracker (332–624), OutcomeMeasurer (935–977)

**Database:**
- `database.py` — anomaly_log schema (666–691), metric_baselines (696–707), decision_log (581–623), compliance_log (624–665), notification_log (761–781), outcome_log (711–727)

**Energy:**
- `domain_coordinators/energy.py` — Cross-check anomaly (1344–1364), circuit anomaly dispatch (1943–1970), NM notify (2554)

**Person:**
- `domain_coordinators/presence.py` — Transition anomalies (376–440), FSM validation (1397), activity logging (1458–1462), outcome tracking (1596–1616)

**Safety:**
- `domain_coordinators/safety.py` — HazardType enum (79–145), detection (1159–1280), signal dispatch (577, 1190)

**Bayesian:**
- `bayesian_predictor.py` — get_anomaly_score() (774–822), record_prediction() (824–846), get_accuracy_stats() (848–887)

**Sensors:**
- `sensor.py` — EnergyCircuitAnomalySensor (5623–5665), Bayesian anomaly binary sensor (1691)

**Activity Log:**
- `activity_logger.py` — ActivityLogger class (37–167)

**Notifications:**
- `domain_coordinators/notification_manager.py` — async_notify() (613–640), notification_log schema (notification_manager.py implicit, database.py:761–781)

**Config / Init:**
- `__init__.py` — repair issue creation (1423–1436)

---

**End of Survey**

---

**Metadata:**
- **Survey Completion:** May 5, 2026
- **Anomaly Touchpoints Found:** 12 distinct touchpoints (AnomalyDetector, Envoy cross-check, circuit anomaly, person transition, Bayesian anomaly, safety hazard, NM alert, activity logger, repair issue, transit validator, + metrics baseline, + decision logger for completeness)
- **Severity Vocabularies:** 8 different schemes (inconsistency confirmed)
- **DB Tables:** 3 anomaly-related (`anomaly_log`, `decision_log`, `compliance_log`, `notification_log`, `ura_activity_log`)
- **Recovery Gaps:** 1 HIGH risk (anomaly_log orphaned rows), 1 MEDIUM (NM notifications), several LOW
- **B7 Reuse Potential:** 100 lines code savings via unified AnomalyEvent schema; net 540 instead of 640 prod lines
- **Recommended Actions:** 4 concrete, prioritized (D0 schema, D1 vocab, D2 cleanup, D3 wire protocol)

