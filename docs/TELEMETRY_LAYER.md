# URA Pseudo-Telemetry Layer

**Audience:** Future maintainers extending or adjusting the dashboard data model.
**Scope:** Everything built across v4.6.10 through v4.6.13 to feed Dashboard v5.0.
**Status:** Living document — update on every sensor add. v4.6.13 is the current floor.

---

## 1. Overview

The URA "telemetry layer" is **not** a metrics platform. It is a layered set of Home Assistant sensor surfaces that read from existing persistent tables (`ura_activity_log`, `compliance_log`, `decision_log`, `anomaly_log`, `metric_baselines`) and existing in-memory coordinator state, and expose them as `sensor.*` entities with structured `extra_state_attributes`. The Dashboard v5.0 React app then consumes those entities via `@hakit/core`'s `useEntity` hook. Calling it "pseudo-telemetry" is honest — there is no separate metrics service, no time-series database, no Prometheus exporter; it is sensors over DAOs.

This layer exists because the React dashboard needs five categories of data that the legacy URA platform did not surface as first-class sensors: setup health, health rollups across coordinators, house-level aggregations, per-coordinator decision telemetry, and anomaly summaries. Rather than building a separate API layer, the v4.6.10–v4.6.13 cycles wired each category into the HA state machine. The dashboard then talks to HA, not to URA directly — a single, well-understood transport (WebSocket + REST), zero new auth.

The result: ~30 new sensor entities across four cycles, all backed by either signal-driven (`SIGNAL_ACTIVITY_LOGGED`, `SIGNAL_DATABASE_READY`) or interval-driven refresh, all surfacing through the same `useEntity().attributes` shape that the dashboard already uses for everything else.

---

## 2. The Data Substrate

The persistent tables the telemetry layer reads from. All are created in `database.py`'s initial schema setup.

### `ura_activity_log`
- **Schema:** `database.py:990-1008`. Columns: `id`, `timestamp` (tz-aware ISO via `dt_util.utcnow().isoformat()`), `coordinator`, `action`, `room`, `zone`, `importance` (`info`/`notable`/`critical`), `description`, `details_json`, `entity_id`.
- **Indexes:** `idx_activity_log_timestamp`, `idx_activity_log_coordinator` (covers `(coordinator, timestamp)`).
- **Writer:** `activity_logger.py:49-132` (`ActivityLogger.log`). All emits route through this single chokepoint.
- **Emit shape (the canonical dispatched payload):** `activity_logger.py:120-129`. Dict keys: `coordinator`, `action`, `description`, `room`, `zone`, `importance`, `timestamp`, `entity_id`.
- **Dedup contract:** `activity_logger.py:27-31, 134-162`. Per-`(coordinator, action, room, description)` key, window varies by importance (30s/60s/300s). Sensors that subscribe to `SIGNAL_ACTIVITY_LOGGED` are downstream of dedup — they will not see suppressed duplicates.
- **Timestamps:** tz-aware (UTC). Format: `dt_util.utcnow().isoformat()`. Readers MUST use `dt_util.parse_datetime`, never `datetime.fromisoformat` alone.
- **Retention:** Daily prune. Cache eviction at `activity_logger.py:156-161` keeps the dedup cache bounded.
- **Readers in the telemetry layer:** D1 (`CoordinatorDecisionsTodaySensor`), D5 (`CoordinatorLastDecisionSensor`), `SafetyEventsSummarySensor`, `URARecentAnomaliesSensor`.

### `compliance_log`
- **Schema:** `database.py:622-695`. Columns: `id`, `timestamp` (tz-**naive** — see below), `decision_id` (FK), `scope`, `device_type`, `device_id`, `commanded_state`, `actual_state`, `compliant` (bool), `deviation_details`, `override_detected` (bool), `override_source`, `override_duration_minutes`.
- **Indexes:** `idx_compliance_decision`, `idx_compliance_timestamp`, `idx_compliance_scope`.
- **Writer:** `coordinator_diagnostics._compare_states` populates rows via the `log_compliance_check` DAO. Each row represents a commanded-vs-actual device-state check the diagnostics watchdog performed against a `decision_log` row.
- **Timestamp caveat:** Written tz-naive (`datetime.utcnow().isoformat()` historically). v4.6.13 D2/D3 queries strip tzinfo from their cutoffs to match: `cutoff = (dt_util.utcnow() - timedelta(hours=24)).replace(tzinfo=None).isoformat()`. **If you read this table from a new sensor, you MUST do the same.** This is the most common bug surface for new readers.
- **Guarantees:** `compliant` is a boolean (0/1). `override_detected` is a boolean (0/1). `decision_id` JOINs back to `decision_log.id`. A row with `override_detected=1` but `compliant=1` is legal (user overrode but then matched the new state).
- **Readers in the telemetry layer:** D2 (`CoordinatorOverrideFrequencySensor`), D3 (`CoordinatorComplianceRateSensor` via `get_compliance_rate`).

### `decision_log`
- **Schema:** `database.py:580-620`. Columns: `id`, `timestamp`, `coordinator_id`, `decision_type`, `scope`, `situation_classified`, `urgency`, `confidence`, `context_json`, `action_json`, `expected_savings_kwh`, `expected_cost_savings`, `expected_comfort_impact`, `constraints_published`, `devices_commanded`.
- **Indexes:** `idx_decision_timestamp`, `idx_decision_coordinator`, `idx_decision_scope`.
- **Writer:** Coordinator decision logging via the `log_decision` DAO.
- **Role in telemetry:** This is the join target for D2 (override frequency) — `compliance_log JOIN decision_log ON c.decision_id = d.id WHERE d.coordinator_id IN (...)`. The telemetry layer treats `decision_log.coordinator_id` as the source of truth for which UI coordinator a compliance/override event belongs to.

### `anomaly_log`
- **Schema:** `database.py:664-700`. v4.6.7 relaxed 5 metric columns to NULL: `observed_value`, `expected_mean`, `expected_std`, `z_score`, `sample_size`. Before v4.6.7 these were NOT NULL with 0.0 sentinels — the sentinels masked the difference between "baseline not yet learned" and "legitimate 0.0".
- **Indexes:** `idx_anomaly_timestamp`, `idx_anomaly_coordinator`, `idx_anomaly_scope`, `idx_anomaly_severity`.
- **Writer:** `AnomalyDetector.store_event` → `database.save_anomaly_event` (`database.py:4585`). Dispatched payload mirrors v4.6.6's `AnomalySeverity` vocabulary (`nominal/advisory/alert/critical`).
- **NULL semantics:** Sentinels in `metric_columns` mean "shape broken — likely payload bug, like the v4.6.1.1 incident." Live validation must check at least one row has non-NULL values within an hour of restart.
- **Readers in the telemetry layer:** `URARecentAnomaliesSensor` (`sensor.py:10317-10523`).

### `metric_baselines`
- **Schema:** `database.py:705-717`. PRIMARY KEY `(coordinator_id, metric_name, scope)`. Columns: `mean`, `variance`, `sample_count`, `last_updated`. Stores Welford running stats (single-pass, numerically stable mean+variance).
- **Writer:** `AnomalyDetector.save_baselines` (`coordinator_diagnostics.py:1104+`). Called at coordinator teardown (peers) or per-observation (CM, per v4.6.11 B.M1 — see below). `INSERT OR REPLACE` on PK collision.
- **Reader:** `AnomalyDetector.load_baselines` (`coordinator_diagnostics.py:1024+`). Called once per coordinator at construction. Orphan-prunes baselines whose metric_name no longer appears in the coordinator's `metric_names` registry.
- **Lifecycle:** Pre-v4.6.11, CM's `_setup_anomaly_detector` constructed but neither loaded nor saved — the baseline reset every boot, making the `minimum_samples=10` gate permanently unreachable (v4.6.10 review CRITICAL: "Ephemeral Baseline / Phantom Feature").
- **Cadence note (Review B.M1 v4.6.11):** Peer coordinators save at teardown because their metrics fire many times per session. CM saves after every observation because `setup_duration_seconds` fires exactly once per boot — teardown-only save would lose the observation if HA crashes before clean shutdown. **Do not "align" CM to the peer pattern.** The code comment at `__init__.py:2085-2090` documents the intent.

---

## 3. In-Memory Signals

URA uses HA's dispatcher for cross-coordinator and cross-platform notification. The telemetry layer subscribes to three signals.

### `SIGNAL_ACTIVITY_LOGGED`
- **Defined:** `domain_coordinators/signals.py:23`.
- **Dispatched:** `activity_logger.py:120-129` (single chokepoint — every activity emit goes through here).
- **Payload:** Dict with keys `coordinator`, `action`, `description`, `room`, `zone`, `importance`, `timestamp`, `entity_id`.
- **Canonical subscriber pattern:** `URARecentAnomaliesSensor.async_added_to_hass` at `sensor.py:10358-10390`. Uses `hass.add_job(self._async_refresh())` — **not** `async_create_task`. See section 5.3 for why.
- **Thread context:** Can fire from a sync worker thread (`activity_logger.log` is awaited from coordinator code that may originate in an executor). All handlers MUST be safe for non-event-loop dispatch.

### `SIGNAL_DATABASE_READY`
- **Defined:** `domain_coordinators/signals.py:28`.
- **Dispatched:** One-shot, from `__init__.py:766` and `__init__.py:2378` immediately after `hass.data[DOMAIN]["database"]` is assigned.
- **Payload:** None (sentinel-only).
- **Purpose:** Closes the race between the CM entry's sensor setup (which adds entities to platforms) and the room entries' DB initialization (which assigns `hass.data[DOMAIN]["database"]`). The CM entry can come up before the room entries finish.
- **Canonical subscriber pattern:** `sensor.py:10398-10416`. If `hass.data[DOMAIN]["database"]` is already populated at `async_added_to_hass`, run an immediate refresh. Otherwise subscribe to `SIGNAL_DATABASE_READY`, run the refresh once on dispatch, then auto-unsubscribe (signal is one-shot, but defensive unsub avoids redundant refreshes on URA reload).
- **Required for:** Any sensor that does a DB read in its initial refresh path. v4.6.13's D2/D3 missed this initially — Review B.B1/C.M2 caught it and added the fallback.

### `SIGNAL_COORDINATOR_MANAGER_READY` — **does not exist**
The brief described this signal as part of the v4.6.10 telemetry stash. **It is not in the codebase.** `signals.py` defines `SIGNAL_NM_READY` and `SIGNAL_BAYESIAN_READY` (v4.6.9), but no `SIGNAL_COORDINATOR_MANAGER_READY`. The setup_telemetry data is read passively from `hass.data[DOMAIN]["setup_telemetry"]` (`__init__.py:2031`) — no signal fires. If a future cycle wants to wake CM-device buttons after CM finishes initializing, follow the `SIGNAL_NM_READY` precedent at `signals.py:59-64`.

---

## 4. The Sensor Layer

### Group A — Setup telemetry (v4.6.10)

#### `URASetupDurationSensor` — `sensor.py:10526-10588`
- **Entity ID:** `sensor.ura_setup_duration_seconds`. Device: CM.
- **Returns:** Seconds (float, 3-decimal). `device_class=DURATION`, `state_class=MEASUREMENT`, `entity_category=DIAGNOSTIC`.
- **Attributes:** `started_at`, `completed_at`, `coordinator_count`, `room_count`.
- **Source:** `hass.data[DOMAIN]["setup_telemetry"]` (stashed at `__init__.py:2031-2044`).
- **Cleared:** `__init__.py:2587-2590` (`async_unload_entry` pops the dict — v4.6.10 review B.B2 fix for bug class #36 lifecycle teardown).
- **Cost:** Pure dict read in `native_value`. Zero DB load.

#### Boot anomaly observation pipeline (v4.6.10 scaffold → v4.6.11 D1 live)
- **CM-level `AnomalyDetector`:** `manager.py:147-161` constructs `_setup_anomaly_detector` with `metric_names=["setup_duration_seconds"]`, `minimum_samples=10`.
- **Persistence wiring (v4.6.11 D1):** `manager.py.async_start` calls `await self._setup_anomaly_detector.load_baselines()` at construction; the per-observation hook at `__init__.py:2076-2091` calls `record_observation` → `save_baselines` (always — even when no anomaly returned, per v4.6.10 critical) → conditional `store_event(AnomalyEvent(...))` dispatch when an anomaly is returned.
- **House state on payload (v4.6.11 A.M3):** `__init__.py:2103-2119`. CM anomaly_log rows now carry `payload["house_state"]` so analytics queries grouping by house_state include CM rows.
- **NM cascade:** Intentionally absent (Review B.L1). Setup duration is internal instrumentation, not an operator alert. Analytics consumers read `anomaly_log` directly; `URARecentAnomaliesSensor` aggregates for the dashboard.

### Group B — Health rollup attributes (v4.6.11 Cycle A — D4)

10 attributes spread across existing sensor classes. The `_SEVERITY_RANK` module constant at `domain_coordinators/manager.py:44-49` is the authoritative AnomalySeverity → rank mapping (hoisted to module level so it is not rebuilt on every `get_summary` call — v4.6.11 A.M2/C.L4).

| Host class | File:Line | Attribute(s) | Source |
|---|---|---|---|
| `CoordinatorSummarySensor` | via `manager.get_summary()` at `manager.py:558-617` | `health_status` (`green`/`orange`/`red`), `status_per_coordinator` (dict per coord: `{status, active_anomalies, enabled}`) | `_SEVERITY_RANK` applied to each coord's `anomaly_detector.get_worst_severity()`; `active_anomalies` comes from `_persisted_active_anomalies()` (filters out suppressed metrics per v4.6.11 A.M1) |
| `RoomsOccupiedSensor` | `aggregation.py` (`RoomsOccupied` extra_state_attributes) | `per_zone_breakdown` (dict: zone → occupied room count) | Reads `CONF_ZONE` from `entry.options` first then `entry.data` (bug class #14) |
| `OccupiedBinarySensor` | `binary_sensor.py` (existing class, extended attrs) | `idle_duration` (seconds since last occupied; 0 when on), `current_persons` (list[str], `[]` not None) | `STATE_TIME_SINCE_OCCUPIED` from coordinator data; `person_coordinator.get_room_occupants(room_name)` for persons |
| `WholeHousePowerSensor` | `aggregation.py` | `source_breakdown` (`{solar_power_w, battery_power_w, grid_power_w}`) | v4.6.11 ships solar wired; battery/grid return None until `CONF_BATTERY_POWER_SENSOR` / `CONF_GRID_POWER_SENSOR` keys are added (deferred to a later cycle) |
| `HVACModeSensor` | via `hvac.get_mode_attrs()` at `hvac.py` (`get_mode_attrs`) | `zone_limits` (dict: zone → `{cool_low, heat_high}`) | Reads `_zone_manager.zones.items()` rather than `get_state_snapshot()` (plan deviation, functionally correct per v4.6.11 C.M3) |
| `SafetyEventsSummarySensor` | `sensor.py:10596-10698` (new class) | `auto_dismissed_count`, `last_event_at`, `window_hours` (=24) | `ura_activity_log` 24h query; 60s cache; refresh task tracked + cancelled in teardown |

The single most important architectural detail: **`SafetyEventsSummarySensor` uses `db._db_read()`, not `db._db()`** (`sensor.py:10638`). Pre-review the code had `db._db()` — the serialized write queue context manager — which would have occupied a write slot every 60s and blocked real writes (`save_baselines`, `save_anomaly_event`, `activity_logger`). Review A.H1/C.H3 caught this. See section 5.3.

### Group C — Aggregator sensors (v4.6.12 Cycle B)

All three live in `aggregation.py` and inherit from `AggregationEntity` + `SensorEntity`. None do DB reads. None have teardown overrides. None hold subscriptions.

#### `ZoneMotionEventCountSensor` — `aggregation.py:4802-4862`
- **Entity ID:** `sensor.universal_room_automation_zones_with_motion`. Unit: `zones`.
- **Returns:** Integer count of distinct zones with at least one room whose `_last_motion_time` is within `ZONE_MOTION_WINDOW_SECONDS` (300s).
- **Attributes:** `zones` (sorted list of zone names), `window_minutes` (5).
- **Extract-helper pattern (v4.6.12 C.C2 — TOCTOU safety):** `_compute_zones_with_motion()` at `aggregation.py:4821` is called by both `native_value` (line 4852) and `extra_state_attributes` (line 4858). Single snapshot, no divergence possible. Pattern to follow for any sensor where the same computation feeds the state and the attrs.
- **Handles bug class #21:** Naive `_last_motion_time` is tolerated via `.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)`.

#### `HouseSystemDemandSensor` — `aggregation.py:4863-4941`
- **Entity ID:** `sensor.universal_room_automation_hvac_system_demand`. Unit: `%`.
- **Formula:** `(active_zone_count / total_zone_count) * 100`, where `active` = `z.hvac_action in ("cooling", "heating")` on `hvac.zone_manager.zones`. Mirrors the same `hvac_action` enumeration used by the anomaly path at `hvac.py:1511`.
- **Returns None when:** HVAC coordinator missing, zero zones configured (no div-by-zero). Bug class #7: None ≠ 0%.
- **Attributes:** `active_zones`, `active_count`, `total_zones`, `load_bucket` (`idle`/`light`/`moderate`/`heavy`), `formula`. The `load_bucket` is computed locally from the already-fetched `zones` snapshot — not by calling `self.native_value` (v4.6.12 C.M3 fix).

#### `EnergyGridDemandSensor` — `aggregation.py:4942+`
- **Entity ID:** `sensor.universal_room_automation_energy_grid_demand`. Unit: `%`.
- **Formula:** `(grid_kw / cap_kw) * 100`. Mirrors `energy.py:1453`'s `max(net_power_w or 0, 0) / 1000.0` exactly so this sensor does not diverge from the anomaly/EV-pausing path.
- **No clamp at 100%:** If real import is 16 kW against an 8 kW cap, this sensor reports 200%. Per `feedback_post_deploy_ordering` — surface excess intentionally. The dashboard renders a 100% bar with an overflow indicator.
- **Returns None when:** EC missing, cap disabled, cap = 0, `net_power_w` unavailable. `available` property gates on EC presence + cap enable.
- **Attributes:** `grid_import_kw`, `grid_import_cap_kw`, `grid_import_cap_enabled`, `exporting` (bool — when `net_w < 0`).

### Group D — Coordinator telemetry (v4.6.13 Cycle C — 21 sensors)

All 21 are registered in `sensor.py` `async_setup_entry` (CM branch only) at `sensor.py:289-307`, iterating `UI_COORDINATORS` from `coordinator_telemetry_const.py:34`. **This iteration site is the seam where a 6th UI coordinator gets added.**

The UI→emit mapping at `coordinator_telemetry_const.py:24-30`:
```python
COORDINATOR_EMIT_LABELS: Final[dict[str, tuple[str, ...]]] = {
    "presence": ("presence", "transit", "room"),  # transit + room are presence-driven
    "hvac": ("hvac",),
    "energy": ("energy",),
    "safety": ("safety",),
    "security": ("security",),
}
```

`compliance` and `notification` emit-labels are deliberately unmapped — they are meta-events that would double-count if rolled up.

#### D1 — `CoordinatorDecisionsTodaySensor` × 5 — `sensor.py:10717-10839`
- **Entity ID:** `sensor.ura_coordinator_manager_{ui_coord}_decisions_today`. Unit: `decisions`.
- **Returns:** Integer count of `ura_activity_log` rows since local midnight where `coordinator IN COORDINATOR_EMIT_LABELS[ui_coordinator]`.
- **Refresh:** Signal-driven on `SIGNAL_ACTIVITY_LOGGED`, filtered by emit-label match (so a `notification` emit does not trigger a refresh on the `presence` sensor). In-flight guard + `_refresh_pending` mirror `URARecentAnomaliesSensor`.
- **Initial load:** Immediate if DB is ready; else subscribe to `SIGNAL_DATABASE_READY` and refresh once on dispatch.
- **Bug class #11 (UTC vs local date):** Uses `dt_util.start_of_local_day()` then `dt_util.as_utc(...)` for the cutoff. The `ura_activity_log.timestamp` column is tz-aware UTC so this comparison is correct.

#### D2 — `CoordinatorOverrideFrequencySensor` × 5 — `sensor.py:10840-10953`
- **Entity ID:** `sensor.ura_coordinator_manager_{ui_coord}_override_frequency`. Unit: `overrides`.
- **Returns:** Integer count of `compliance_log` rows in the last 24h where `override_detected = 1` joined to `decision_log.coordinator_id IN COORDINATOR_EMIT_LABELS[ui_coordinator]`.
- **Refresh:** Time-based, every 5 min (`OVERRIDE_FREQUENCY_REFRESH_S = 300`). Compliance writes do not dispatch a signal — polling is the only option.
- **Tz-naive caveat:** `compliance_log.timestamp` is tz-naive. The cutoff strips tzinfo: `(dt_util.utcnow() - timedelta(hours=24)).replace(tzinfo=None).isoformat()`. **If you copy this sensor for a new compliance reader, copy the tzinfo strip.**
- **Database-ready fallback (v4.6.13 B.B1/C.M2 fix):** Subscribes to `SIGNAL_DATABASE_READY` if DB is missing at `async_added_to_hass`, mirroring D1/D5.

#### D3 — `CoordinatorComplianceRateSensor` × 5 — `sensor.py:10954-11088`
- **Entity ID:** `sensor.ura_coordinator_manager_{ui_coord}_compliance_rate`. Unit: `%`.
- **Returns:** Float 0-100, or **None** when there are zero decisions in the 7-day window.
- **None-on-zero contract (v4.6.13 D3):** This is the most important Boolean in the cycle. `get_compliance_rate` returns 1.0 (100%) when total is 0. A fresh-install dashboard would render "100% compliance" before any decisions exist — misleading. The sensor explicitly overrides to None when `decisions_in_window == 0`. The attribute `decisions_in_window` is exposed so the UI can render "no data" instead of "unknown".
- **Aggregation across emit labels:** For UI `"presence"` (3 emit labels), the sensor loops `get_compliance_rate(coordinator_id=label)` three times, sums compliant + total, then computes the rate. Per-refresh: 7 DAO calls max across 5 sensors × 2 refreshes/hour = 14 queries/hour.
- **Refresh:** Time-based, every 30 min (`COMPLIANCE_RATE_REFRESH_S = 1800`). Compliance rate is a slow-moving 7-day metric.

#### D4 — `URADBSizeSensor` × 1 — `sensor.py:11089-11164`
- **Entity ID:** `sensor.ura_coordinator_manager_db_size`. Unit: `MB`.
- **Returns:** Float MB including WAL + SHM sidecars. SQLite in WAL mode can carry hundreds of MB in the `-wal` file during heavy write bursts — including it gives the user-meaningful number.
- **Refresh:** Time-based, every 5 min (`DB_SIZE_REFRESH_S = 300`). Three sequential `executor_job` calls per refresh (main + `-wal` + `-shm`) — known LOW (`v4.6.13 C.L1`), deferred to a future polish cycle.
- **No DB query:** Filesystem `os.path.getsize` calls. Zero load on the write queue.

#### D5 — `CoordinatorLastDecisionSensor` × 5 — `sensor.py:11165+`
- **Entity ID:** `sensor.ura_coordinator_manager_{ui_coord}_last_decision`. `device_class=TIMESTAMP`.
- **Returns:** ISO timestamp string of the most recent `ura_activity_log` row across mapped emit labels, or None.
- **Attributes:** `action`, `description`, `room`, `zone`, `entity_id` from the row.
- **Refresh:** Signal-driven on `SIGNAL_ACTIVITY_LOGGED`, same emit-label filter as D1.
- **Parses with `dt_util.parse_datetime`** because `ura_activity_log` writes are tz-aware (per `activity_logger.py:66`).

### Group E — Anomaly surfaces

#### `URARecentAnomaliesSensor` — `sensor.py:10317-10523` (v4.6.3 D12)
The **gold-standard signal-driven refresh pattern**. Every new signal-driven sensor in v4.6.10–v4.6.13 was patterned after this class. Key features:
- `SIGNAL_ACTIVITY_LOGGED` subscription with action-filter (`action == "anomaly"`).
- `hass.add_job(self._async_refresh())` — never `async_create_task` (see 5.3).
- In-flight guard (`_refresh_in_flight`) + pending flag (`_refresh_pending`) prevents burst-fire pile-ups.
- One-shot `SIGNAL_DATABASE_READY` fallback for the startup race.
- All unsubscribes captured via `async_on_remove` (bug class #38).

#### `SafetyEventsSummarySensor` — `sensor.py:10596-10698` (v4.6.11 D4.8)
See Group B. Uses a 60s cache rather than signal-driven refresh because safety emits are infrequent and the cache is cheap; the `native_value` property triggers an async refresh task when stale (tracked via `self._refresh_task` per Review C.C2 to prevent re-entry pile-ups).

#### `AnomalyDetector.load_baselines` / `save_baselines` (v4.6.11 D1)
`coordinator_diagnostics.py:1024+` and `:1104+`. The persistence half of the Welford-stats baseline. Wired into 6 coordinators (safety, hvac, presence, security, music_following, **and now coordinator_manager** via v4.6.11 D1). The CM wiring is the only one with a per-observation save cadence — see the comment block at `__init__.py:2085-2090`.

---

## 5. Synthesis Layer

### 5.1 The Composition Model — How a Dashboard Tile is Fed

Use the **Diagnostics tab "Decisions today: 89" tile** as the canonical end-to-end example.

1. **Coordinator emits a decision.** A `presence` coordinator transitions a room. Somewhere in `presence.py` it calls `await self._activity_logger.log(coordinator="presence", action="room_occupied", description="Master bedroom occupied", room="master_bedroom", importance="info")`.

2. **`ActivityLogger.log` runs** (`activity_logger.py:49-132`). Dedup check (`_should_log` at line 134) returns True (no recent identical event). Three things happen:
   - DB write via `database.log_activity` (`database.py:4227`) — synchronous against the write queue, hits `idx_activity_log_coordinator` on the way in.
   - HA event fire: `hass.bus.async_fire("ura_action", ...)` for logbook integration.
   - **Dispatcher send:** `async_dispatcher_send(self.hass, SIGNAL_ACTIVITY_LOGGED, payload)` at line 120.

3. **`CoordinatorDecisionsTodaySensor("presence")` wakes** (`sensor.py:10717+`). Its `_handle_activity_logged` subscriber checks `payload["coordinator"] in COORDINATOR_EMIT_LABELS["presence"]` (= `("presence", "transit", "room")`). Match. In-flight guard: `_refresh_in_flight` is False → schedule via `hass.add_job(self._async_refresh())`.

4. **`_async_refresh` runs on the event loop** (scheduled via `add_job`, which is thread-safe). Sets `_refresh_in_flight = True`, opens a read connection: `async with database._db_read() as db`, runs the count query against `idx_activity_log_coordinator` with the local-midnight cutoff. Result: `89`.

5. **`self._count_today = 89; self.async_write_ha_state()`**. HA's state machine writes the new state. The `_refresh_in_flight` finally block clears the flag and re-fires if `_refresh_pending` was set during the run.

6. **HA state machine propagates** the new state value. WebSocket pushes `state_changed` event to all connected clients.

7. **Dashboard React app**: `useEntity("sensor.ura_coordinator_manager_presence_decisions_today")` hook fires a re-render. The Diagnostics tile reads `entity.state` (= "89") and any `entity.attributes` (timestamp, etc.). Component re-renders.

That is the loop. **A telemetry tile is fed by:** coordinator action → ActivityLogger → DB write + dispatcher → sensor refresh → HA state machine → WebSocket → useEntity → React component. No special API, no separate transport, no auth duplication.

### 5.2 Where the Seams Are

If you are adding new dashboard data, find the seam in this table first. The seam closest to the data minimizes the blast radius.

#### Add a new UI coordinator (6th card on the dashboard)
- **File:** `domain_coordinators/coordinator_telemetry_const.py`. Add one entry to `COORDINATOR_EMIT_LABELS` and one to `UI_COORDINATORS`. That is the entire data-model change.
- **Code:** Zero changes to `sensor.py`. The async_setup_entry block at `sensor.py:289-307` iterates `_UI_COORDINATORS` and instantiates all five sensor classes (D1, D2, D3, D5) per coordinator. Adding a name to the tuple gives you 20 new entities (4 × N coordinators) for free.
- **Risk:** Make sure the new emit label actually appears in `ura_activity_log.coordinator` — grep `activity_logger.log` call sites. If your coordinator never emits, all four sensors will sit at 0.

#### Add a new metric attribute on an existing sensor
- **File:** Wherever the sensor class lives. Drop the attribute into `extra_state_attributes`.
- **Rule:** **No DB reads in `extra_state_attributes`.** This property is called every time HA writes state, every time a UI reads the entity, every time the state machine ticks. Compute from already-fetched state held on `self`. If the data is not on `self`, refresh during `native_value` or via a signal handler, not in attrs. See bug class #26.
- **Pattern:** v4.6.12 C.M3 fix. `HouseSystemDemandSensor.extra_state_attributes` originally called `self.native_value` (which re-fetched coordinators and re-iterated zones). Fix: compute pct locally from the already-fetched `zones` snapshot.

#### Add a new aggregator sensor
- **File:** `aggregation.py`. Subclass `AggregationEntity` + `SensorEntity`.
- **Register:** Add an instantiation in `async_setup_aggregation_sensors` (around `aggregation.py:199`).
- **Pattern (v4.6.12 extract-helper):** If the same computation feeds both `native_value` and `extra_state_attributes`, write a `_compute_*()` private method and call it from both. See `_compute_zones_with_motion` at `aggregation.py:4821`. Prevents TOCTOU divergence.
- **Cost:** AggregationEntity gives you 30s polling by default. No signal subscriptions needed unless the data changes faster than 30s.

#### Add a new coordinator telemetry sensor (per-UI-coordinator pattern)
- **File:** `sensor.py`. Mirror one of `CoordinatorDecisionsTodaySensor` (signal-driven) or `CoordinatorOverrideFrequencySensor` (polling).
- **Choose signal-driven when:** The underlying event dispatches `SIGNAL_ACTIVITY_LOGGED` (i.e., the data is in `ura_activity_log`). Filter by emit-label match in the handler.
- **Choose polling when:** Data lives in `compliance_log`, `decision_log`, or any table without a dispatcher signal. Use a constant in `coordinator_telemetry_const.py` for the interval.
- **Always:** In-flight guard, `SIGNAL_DATABASE_READY` fallback for startup race, `_db_read()` for SELECT.
- **Register:** Loop in the CM branch of `async_setup_entry` at `sensor.py:289-307`.

#### Add a new persistent metric (new column or new table)
- **Tier:** This is Tier 2-DB. See CLAUDE.md. Three reviewers, framed at data integrity, migration correctness, new surfaces.
- **Reuse before adding:** Welford stats? `AnomalyDetector` already does it — just add a `metric_name` to the registry. Commanded-vs-actual outcomes? `ComplianceTracker` already does it. Anomaly events? `store_event(AnomalyEvent(...))` already lands in `anomaly_log`.
- **If you must add a column:** Update `database.py`'s `_create_table_safe` block. Add a migration block (see compliance_log `scope` migration at `database.py:643-653` as the canonical example). Bump `PRAGMA user_version`. Pre-deploy: capture row-rate snapshot per Tier 2-DB protocol.

### 5.3 Anti-Patterns to Avoid (Lessons from 13 Cycles)

#### Don't do DB reads in `extra_state_attributes`
Bug class #26. `extra_state_attributes` is called on every state read. If you query the DB there, you pile up queries proportional to UI poll rate × number of subscribers. Compute from already-fetched `self.*` state, or schedule a refresh in `native_value` (which is also hot, but at least is the natural cache miss point).

#### Don't use `_db()` for SELECT — use `_db_read()`
`v4.6.11 A.H1`. `db._db()` is the serialized write context manager. Using it for a SELECT occupies a write queue slot. With a 60s cache TTL, that is once a minute, blocking real writes (`save_baselines`, `save_anomaly_event`, `activity_logger`). `db._db_read()` is the read-only connection (SQLite WAL mode supports concurrent reads). Every sensor SELECT in the codebase now uses `_db_read`.

#### Don't `async_create_task` from a signal handler
`v4.6.3.2 wedge; reaffirmed v4.6.13 A.L1`. `SIGNAL_ACTIVITY_LOGGED` can fire from a sync worker thread. `hass.async_create_task` from a non-event-loop thread raises `RuntimeError` under `ReportBehavior.ERROR` for custom integrations. Use `hass.add_job(coroutine)` — thread-safe.

The v4.6.13 review A.L1 explicitly DECLINED to "consistency-fix" the signal handlers to `async_create_task` because reviewer B caught the regression risk. **Polling sensors use `async_create_task` because `async_track_time_interval` fires on the event loop. Signal handlers use `add_job`. Different contexts, different choices, by design.**

#### Don't return 1.0 / 100% on zero-sample compliance — return None
`v4.6.13 D3 contract`. A fresh install with zero decisions has no compliance data. Reporting 100% would render a misleading "perfect score" on the dashboard. Return None, expose the count via `extra_state_attributes["decisions_in_window"]`, and let the UI render "no data".

#### Don't override `async_will_remove_from_hass` without calling `super()`
`v4.6.11 C1 (bug class #38 — lost unsubscribe)`. `AggregationEntity.async_will_remove_from_hass` cleans up `_agg_retry_unsub` (a 5s startup-retry timer). If your override skips `super()`, that timer leaks. Always: `await super().async_will_remove_from_hass()` as the first line.

#### Don't fire untracked `async_create_task` from a sync property
`v4.6.11 C2 (bug class #19)`. `native_value` is a `@property` that can be hit at any frequency. Firing a fire-and-forget refresh task with no reference, no re-entry guard, and no teardown cancel means multiple stale-cache reads pile up overlapping queries. Track the task on `self._refresh_task`, guard with `if self._refresh_task is None or self._refresh_task.done()`, cancel in teardown. See `SafetyEventsSummarySensor` at `sensor.py:10676`.

#### Don't compute the same thing twice in `native_value` AND `extra_state_attributes` — extract a helper
`v4.6.12 C.C2`. TOCTOU risk between the two property reads (the state machine may capture state and attrs at slightly different times under fast events). Extract a `_compute_*()` method. Both properties call it. Snapshot, single source of truth, no divergence.

#### Don't read `entry.data` without falling back to `entry.options`
Bug class #14 (stale config snapshot). `entry.options` reflects post-options-flow updates; `entry.data` is the original setup. Always: `entry.options.get(KEY) or entry.data.get(KEY)`. The v4.6.12 ZoneMotionEventCountSensor reads `CONF_ZONE` this way on every `native_value` call so a zone rename takes effect without integration reload.

#### Don't use `datetime.utcnow()` — `dt_util.utcnow()` always
Bug class #21. `datetime.utcnow()` is tz-naive and deprecated. `dt_util.utcnow()` returns tz-aware UTC. The compliance_log tz-naive caveat (section 4 group D D2) is the one exception where you write the column as naive — and even then, the cutoff comparison strips tzinfo from a `dt_util.utcnow()` result rather than introducing a raw `datetime.utcnow()`.

---

## 6. Open / Outstanding

### Test-infrastructure debt (v4.6.11 C.H2 + v4.6.12 C.C1)
Behavioral tests for new sensors currently use inline replica classes (`_make_*_sensor()` helpers that re-implement sensor logic) plus AST smoke tests that verify production class structure. The real refactor — mock-patching `_get_room_coordinators` / `_get_hvac_coordinator` / `_get_energy_coordinator` to drive the real classes through behavioral tests — is deferred. Same class as v4.6.11's `_SEVERITY_RANK` string-vs-enum key divergence: tests pass today because `AnomalySeverity` is a `StrEnum` and dict-key equality works against both forms. **Future cycle should drive production code paths, not replicas.**

### Compliance_log JOIN compound index (v4.6.13 A.M1)
D2 and D3 join `compliance_log` to `decision_log` filtered by `c.timestamp` and `d.coordinator_id`. SQLite picks one index per table-scan; current single-column indexes are fine at ~50k rows. Past ~200k rows the planner could lose the index race. **Defer the schema cycle until row count > ~200k.** Recommended index when ready: `CREATE INDEX IF NOT EXISTS idx_compliance_decision_ts ON compliance_log(decision_id, timestamp)`.

### D2/D3 database-ready fallback (v4.6.13 B.B1 / C.M2)
**SHIPPED in v4.6.13.** Pattern now consistent across D1, D2, D3, D5: check `hass.data["database"]` at `async_added_to_hass`; if absent, subscribe to `SIGNAL_DATABASE_READY` for one-shot fallback. Any new DB-reading sensor must follow this pattern.

### Setup_telemetry persistence across restarts
Explicit non-goal. Each boot's value stands alone. The baseline accumulates via the Welford persistence path (`metric_baselines`). If we ever wanted multi-boot trend visualization, HA's history UI already covers it from the sensor's state history.

### NM push notification for CM self-instrumentation
Explicit non-goal at this layer. CM's setup_duration anomalies land in `anomaly_log` and surface via `URARecentAnomaliesSensor`. No operator alert. v4.7+ enhancement if instrumentation events ever need user-facing surfacing.

### Source breakdown gap on WholeHousePowerSensor
`source_breakdown.battery_power_w` and `grid_power_w` return None until `CONF_BATTERY_POWER_SENSOR` and `CONF_GRID_POWER_SENSOR` config keys are added. Filed as backlog. Solar wired and working.

### Live `db_size` sensor reports `unknown` (2026-05-19 post-deploy observation)
The `URADBSizeSensor` returns `unknown` post-restart despite `database.db_file` being a real attribute path (`database.py:42`). Investigation candidate: likely the `getattr(database, "db_file", None)` returns falsy early in setup OR `async_add_executor_job(os.path.getsize, ...)` is raising an exception under WAL writes. Fix candidate: log on the exception path so live diagnosis is possible without a code dive. Filed for a hotfix.

---

## 7. Recall Hints

| Question | Section |
|---|---|
| "Where do I add a new dashboard sensor?" | 5.2 |
| "Why did v4.6.13 NOT use `async_create_task` in signal handlers?" | 5.3 (third anti-pattern) + v4.6.13 review A.L1 |
| "How does the dashboard get its data?" | 5.1 |
| "Why is compliance_log timestamp tz-naive when ura_activity_log is tz-aware?" | 4 (substrate caveat under `compliance_log`) |
| "How do I add a 6th UI coordinator card?" | 5.2 (first seam) |
| "What's the canonical signal-driven refresh pattern?" | 4 Group E (`URARecentAnomaliesSensor`) |
| "Why does CM save baselines per-observation when peers save at teardown?" | 2 (`metric_baselines` cadence note) |
| "What guards prevent burst-fire pile-ups?" | 4 Group E (in-flight + pending flag) |
| "Where do new persistent metrics go?" | 5.2 (last seam — Tier 2-DB ceremony) |
