# v4.6.11 — D3 Persistence + Dashboard Attribute Adds + LOW Polish

**Tier:** **Tier 2** (revised from initial brief's Tier 2-DB framing — see Decision Gate 1 below)
**Branch:** `feature/v4.6.11-d3-persistence-and-attrs`
**Prerequisite tag (before any review-fix commits):** `pre-review-v4.6.11`
**Target deploy:** 2026-05-20 to 2026-05-22

## Decision Gates (resolve BEFORE branch cut)

### Gate 1: D1 path — committed to **Path (b'): replay from existing `metric_baselines` table**

**Discovery during planning:** The brief presents two paths (a: DB schema + persistence; b: query-replay). Both presume the table doesn't exist. **It already exists.**

- `database.py:705-717` — `metric_baselines (coordinator_id, metric_name, scope, mean, variance, sample_count, last_updated)` table is created in the initial schema, PRIMARY KEY `(coordinator_id, metric_name, scope)`.
- `coordinator_diagnostics.py:1018-1096` — `AnomalyDetector.load_baselines()` already implemented (with orphan-pruning logic).
- `coordinator_diagnostics.py:1098-1127` — `AnomalyDetector.save_baselines()` already implemented (INSERT OR REPLACE).
- Every other coordinator already wires this pattern: `safety.py:689`, `hvac.py:534`, `presence.py:638`, `security.py:631`, `music_following.py:170` call `await self.anomaly_detector.load_baselines()` at setup; matching `save_baselines()` calls at `presence.py:2096`, `hvac.py:1740`, `security.py:682`, `music_following.py:567`.
- `manager.py:147-161` — CM's `_setup_anomaly_detector` is constructed but **neither `load_baselines()` nor `save_baselines()` is called anywhere for it**.

**Committed path: (b')** "Hook the CM's `_setup_anomaly_detector` into the existing `load_baselines`/`save_baselines` pattern used by every other AnomalyDetector instance."

**Implications:**
- **No new schema.** No migration. No Tier 2-DB ceremony required.
- The baseline (n, mean, variance per `(coordinator_id, metric_name, scope)`) ALREADY has a persistence row contract — `INSERT OR REPLACE` on PK collision.
- Risk surface is narrow: lifecycle wiring at two points (post-construct load, post-observation save) plus the missing `store_event` after `record_observation`.
- The "10 observations needed" gate (from `minimum_samples=10` at `manager.py:154`) is satisfied because each successful boot saves its updated baseline row, and the next boot loads it. After ~10 healthy boots, the baseline matures.

### Gate 2: D3 (v4.6.9 seed-helpers extraction) — committed to **DEFER to v4.6.12**

Reading `person_coordinator.py:1007-1072`: helpers mutate `self.data[person_name][...]` and depend on the `if self.data is None: return` lifecycle invariant. NOT a clean free-function extraction. Deferred with explicit alternative noted: test-side `unittest.mock.patch` of `homeassistant.components.person` before import resolution would sidestep the extraction entirely.

### Gate 3: Test infra baseline — capture BEFORE pre-review tag

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v --tb=no -q 2>&1 | tail -15
```
Record passed/failed/errors counts for `pre-review-v4.6.11`. Validator subagent should filter the v4.6.11-added test files when generating the diff (per v4.6.10 baseline-diff artifact).

---

## Cycle Summary

| Deliverable | Description | Prod LoC | Test LoC | Tier flavor |
|---|---|---|---|---|
| **D1** | CM `_setup_anomaly_detector` baseline persistence + `store_event(AnomalyEvent(...))` dispatch + scaffold-comment update | ~70 | ~60 | Tier 2 |
| **D2** | LOW carryovers from v4.6.10: factory removal, `asyncio.get_event_loop` cleanup, `dt_util.utcnow` fix | ~15 | ~10 | Tier 2 |
| **D3** | v4.6.9 seed-helpers extraction — **DEFERRED to v4.6.12** (Gate 2) | 0 | 0 | n/a |
| **D4** | Cycle A dashboard attribute adds — 10 items | ~75 | ~90 | Tier 2 |
| **Total** | | **~160** | **~160** | **Tier 2** |

---

## Files Touched

| File | Reason | Deliverable |
|---|---|---|
| `__init__.py` (~2046-2110) | Replace D3 scaffold-only block with live observation push + `store_event` dispatch | D1, D2 |
| `domain_coordinators/manager.py` (~145-165) | Add `load_baselines()` call to CM construction sequence; add `save_baselines()` hook called once post-observation; extend `get_summary()` with `health_status` + `status_per_coordinator` (D4) | D1, D4 |
| `domain_coordinators/coordinator_diagnostics.py` (~796-801, ~824) | Fix `datetime.utcnow()` → `dt_util.utcnow()` (Bug Class #21) at the two existing call sites | D2 |
| `sensor.py` (around `CoordinatorSummarySensor` line 3471, `HVACModeSensor` line 6900, new `SafetyEventsSummarySensor`) | Attribute adds + new safety-events summary class | D4 |
| `aggregation.py` (around `RoomsOccupiedSensor` line 809, `WholeHousePowerSensor` line 2069) | `per_zone_breakdown` + `source_breakdown` attributes | D4 |
| `binary_sensor.py` (`OccupiedBinarySensor` line 174, `extra_state_attributes` line 317-329) | `idle_duration` + `current_persons` attributes | D4 |
| `domain_coordinators/hvac.py` (`get_mode_attrs` at line 1646) | Add `zone_limits` dict to existing return shape | D4 |
| `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py` (NEW) | D1 unit + integration tests | D1 |
| `quality/tests/test_v4_6_11_dashboard_attrs.py` (NEW) | D4 attribute-presence + computation tests | D4 |
| `quality/tests/test_v4_6_10_setup_telemetry.py` | Convert deprecated `asyncio.get_event_loop().run_until_complete()` calls | D2 |

---

## D1 — D3 Anomaly Persistence + Dispatch (~70 prod + ~60 test LoC)

### Phase 1 — Persistence at CM start (`manager.py`, in `async_start` around line 245-275)

After the per-coordinator `async_setup()` loop completes AND after `self._notification_manager` is started (database initialized by then), insert:

```python
# v4.6.11 D1: CM-level anomaly detector baseline persistence.
# Pattern mirrors safety.py:689 / hvac.py:534 / presence.py:638 /
# security.py:631 / music_following.py:170. Without this load,
# the in-memory _baselines dict resets every restart and
# minimum_samples=10 (manager.py:154) is unreachable.
if self._setup_anomaly_detector is not None:
    try:
        await self._setup_anomaly_detector.load_baselines()
        _LOGGER.debug(
            "v4.6.11 D1: CM setup_anomaly_detector baselines loaded"
        )
    except Exception:
        _LOGGER.debug(
            "v4.6.11 D1: CM setup_anomaly_detector load_baselines failed (non-fatal)",
            exc_info=True,
        )
```

### Phase 2 — `store_event` + `save_baselines` after observation (`__init__.py:2063-2108` block)

Replace the scaffold-only `_push_setup_observation` body with live pipeline:

1. `_det.record_observation(...)` — same as today
2. `await _det.save_baselines()` ALWAYS, even when no anomaly returned (regression guard)
3. If `_anomaly is not None`: construct `AnomalyEvent` mirroring `safety.py:1684-1715`, call `await _det.store_event(event)`, and mirror to `activity_logger.log(coordinator="coordinator_manager", action="anomaly", importance="notable", ...)`

### Phase 3 — Update misleading comment at `__init__.py:2048-2057`

Replace "SCAFFOLD ONLY ... no dispatch" block with 6-line pipeline description: construct → load_baselines on async_start → record_observation → save_baselines → store_event → anomaly_log row visible via URARecentAnomaliesSensor.

### NM dispatch trace (verified, not guessed)

- `_det.store_event(event)` → `database.save_anomaly_event(event)` at coordinator_diagnostics.py:985
- Row lands in `anomaly_log` table
- `URARecentAnomaliesSensor` queries `anomaly_log` directly + dispatches to dashboard
- **Honest scope:** No new NM push-notification channel for setup_duration_seconds anomalies this cycle. The row surfaces via existing aggregators. Adding per-coordinator NM channel for self-instrumentation is v4.7+ enhancement.

### D1 Acceptance Criteria

- **Test:** `test_load_baselines_called_on_async_start` — AsyncMock pattern
- **Test:** `test_save_baselines_called_after_observation` — even when anomaly is None
- **Test:** `test_store_event_called_only_when_anomaly_returned`
- **Test:** `test_baseline_persists_across_simulated_restart` — TWO separate AnomalyDetector instances, second loads what first saved, `sample_count == 11`
- **Test:** `test_anomaly_event_payload_shape` — verify NOT NULL columns vs post-v4.6.7 schema
- **Live:** After 10 consecutive HA restarts, `SELECT sample_count FROM metric_baselines WHERE coordinator_id='coordinator_manager' AND metric_name='setup_duration_seconds';` returns ≥ 10
- **Live:** Deliberate slowdown injection (60s sleep in setup) triggers anomaly_log row within 3 subsequent boots; z_score > 2.0
- **Live:** Dashboard's "decisions today" / `URARecentAnomaliesSensor` count reflects the injected anomaly within 60s of restart

---

## D2 — LOW Carryovers from v4.6.10 (~15 prod + ~10 test LoC)

### D2.1 — `_make_observation_coro()` factory removal — VERIFIED NOT APPLICABLE

Current `__init__.py:2063-2108` uses inline `async def _push_setup_observation` — no factory present. v4.6.10 review's L1 referenced an earlier draft that was changed before merge. Documenting for traceability; no code change.

### D2.2 — Replace deprecated `asyncio.get_event_loop().run_until_complete()`

File: `quality/tests/test_v4_6_10_setup_telemetry.py`. Mechanical `asyncio.run(coro)` substitution.

### D2.3 — Fix `datetime.utcnow()` at `coordinator_diagnostics.py:798` and `:824`

- Line 798: `_maybe_reset_daily_counter` — `today = datetime.utcnow().date().isoformat()` → `dt_util.utcnow().date().isoformat()`
- Line 824: `AnomalyRecord(timestamp=datetime.utcnow(), ...)` → `dt_util.utcnow()`
- Add module-top `from homeassistant.util import dt as dt_util` if missing.

### D2 Acceptance Criteria

- **Verify:** No `datetime.utcnow()` calls remain in `coordinator_diagnostics.py`
- **Verify:** No `asyncio.get_event_loop().run_until_complete` in `test_v4_6_10_setup_telemetry.py`
- **Test:** Existing v4.6.10 telemetry tests pass after asyncio.run rewrite
- **Test:** `test_no_datetime_utcnow_in_coordinator_diagnostics` source-inspection (Bug Class #21 sweep)

---

## D3 — Person Seed Helpers Extraction — DEFERRED to v4.6.12

See Gate 2. BACKLOG update entry:

```markdown
### LOW (v4.6.11 deferral, ship v4.6.12 if cleanup remains green)
- `domain_coordinators/person_seed_helpers.py` extraction. v4.6.11 planning found
  helpers depend on `self.data` mutation (person_coordinator.py:1026, 1029, 1056, 1063)
  and the `if self.data is None: return` lifecycle guard (1018, 1050). Free-function
  extraction either drops the guard (wrong), embeds it in the helper (changes contract),
  or splits guard+body across two surfaces. Alternative: test-side `unittest.mock.patch`
  of `homeassistant.components.person` before import resolution.
```

---

## D4 — Cycle A Dashboard Attribute Adds (~75 prod + ~90 test LoC)

### D4.1 — `CoordinatorSummarySensor.health_status` + `status_per_coordinator`

Extend `manager.get_summary()` (line 530) to include:
- `health_status: str` — green/orange/red traffic-light from worst per-coord severity
- `status_per_coordinator: dict[str, dict]` — per coordinator: `{status, active_anomalies, enabled}`

Severity mapping: NOMINAL → green, ADVISORY → orange, ALERT/CRITICAL → red.

Use `getattr(coordinator, "anomaly_detector", None)` for safe access — not all coordinators have one.

### D4.2 — `RoomsOccupiedSensor.per_zone_breakdown`

Extend `extra_state_attributes` (aggregation.py:832) to include `per_zone_breakdown: dict[str, int]` mapping zone → occupied room count. Read `CONF_ZONE` from `entry.options` first then `entry.data` (Bug Class #14 prevention).

### D4.3 — `OccupiedBinarySensor.idle_duration`

Add to existing attrs:
```python
"idle_duration": 0 if self.is_on else (
    self.coordinator.data.get(STATE_TIME_SINCE_OCCUPIED) if self.coordinator.data else None
),
```

`STATE_TIME_SINCE_OCCUPIED` already computed in `coordinator.py:1399`.

### D4.4 — `OccupiedBinarySensor.current_persons`

```python
def _get_current_persons_safe(hass, coordinator) -> list[str]:
    try:
        person_coord = hass.data.get(DOMAIN, {}).get("person_tracking_coordinator")
        if person_coord is None:
            return []
        room_name = coordinator.entry.data.get("room_name", "")
        if not room_name:
            return []
        return person_coord.get_room_occupants(room_name)
    except Exception:
        return []
```

Always return `[]` not None (UI expects array; Bug Class #8).

### D4.5 — `WholeHousePowerSensor.source_breakdown` (HONEST SCOPE)

Add `source_breakdown: dict` with `solar_power_w` / `battery_power_w` / `grid_power_w`. **Honest discovery:** there is NO `CONF_BATTERY_POWER_SENSOR` or `CONF_GRID_POWER_SENSOR` config key today (only `CONF_BATTERY_LEVEL_SENSOR` for SoC and deprecated `CONF_GRID_IMPORT_SENSOR` for energy).

This cycle: `solar_power_w` reads `CONF_SOLAR_PRODUCTION_SENSOR`; `battery_power_w` and `grid_power_w` return None.

**Filed for v4.6.13:** add `CONF_BATTERY_POWER_SENSOR` + `CONF_GRID_POWER_SENSOR` config keys + wiring.

### D4.6 — `HVACModeSensor.zone_limits`

Extend `hvac.get_mode_attrs()` (hvac.py:1646) with:
```python
zone_limits: dict[str, dict[str, float | None]] = {}
try:
    snapshot = self._zone_manager.get_state_snapshot()
    for zone_id, z_attrs in snapshot.items():
        zone_limits[z_attrs.get("friendly_name", zone_id)] = {
            "cool_low": z_attrs.get("target_temp_low"),
            "heat_high": z_attrs.get("target_temp_high"),
        }
except Exception:
    pass
attrs["zone_limits"] = zone_limits
```

Reviewer verify `get_state_snapshot()` shape matches expected per-zone dict.

### D4.7 — Safety detector audit — VERIFIED ZERO MATCHES

Grep found ZERO matches for `smoke_ppm` / `co_ppm` / `battery_percent` / `last_test` anywhere in codebase. Implementing these requires detector entity registration + passthrough design.

**Decision:** **Defer to v4.6.13 Cycle B.** v4.6.11 ships verified audit result in code-review doc + BACKLOG entry. No code change in this cycle for D4.7.

### D4.8 — `SafetyEventsSummarySensor` (new class)

New class in `sensor.py`. Queries `ura_activity_log` for safety coordinator entries in last 24h.

Bug Class #26 mandatory: 60s in-sensor cache before re-query. Bug Class #36: clear cache on entity remove.

State: `events_today_count` (int). Attributes: `auto_dismissed_count`, `last_event_at`, `window_hours`.

Query:
```sql
SELECT COUNT(*),
       SUM(CASE WHEN action LIKE '%dismiss%' OR action LIKE '%auto_clear%' THEN 1 ELSE 0 END),
       MAX(timestamp)
FROM ura_activity_log
WHERE coordinator='safety' AND timestamp >= ?
```

Cutoff: `(dt_util.utcnow() - timedelta(hours=24)).isoformat()`.

### D4 Acceptance Criteria

Per attribute:
- **Test:** `test_<sensor>_<attribute>_present` — attribute key in `extra_state_attributes`
- **Test:** `test_<sensor>_<attribute>_type` — value type matches
- **Test:** `test_<sensor>_<attribute>_computation` — known inputs produce expected output

Specific verifies for each of the 7 attribute adds + 1 new sensor.

**Live:** Dashboard v5.0 shell-out tabs (when wired in D3-D7) read each attribute via `useEntity(...).attributes.<attr_key>` without "[object Object]" or "undefined" artifacts.

**Live:** Inject known safety event, wait 65s, verify `sensor.ura_safety_events_summary` state increments by 1.

---

## Risk Register

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| `load_baselines()` runs before database in hass.data | HIGH | LOW | Database initialized before `coordinator_manager.async_start()`. Pattern verified in safety.py:689. |
| `save_baselines` on every observation = write-queue contention | MEDIUM | LOW | Setup observation fires ONCE per restart. Negligible. |
| `manager.get_summary()` extension references coord.anomaly_detector — not all have one | MEDIUM | MEDIUM | `getattr(coordinator, "anomaly_detector", None)` everywhere. |
| `HVACModeSensor.zone_limits` snapshot shape may differ from get_zone_status_attrs | MEDIUM | MEDIUM | Verify during build. Test against mock zone_manager. |
| `current_persons` lookup by `person_tracking_coordinator` hass.data key | MEDIUM | LOW | Verify the key name in `__init__.py` registration. |
| `SafetyEventsSummarySensor` 24h query slow on large activity log | LOW | LOW | Existing index `idx_activity_log_coordinator` covers WHERE clause. 60s cache. |
| AnomalySeverity → NewSev mapping for NOMINAL | LOW | LOW | `record_observation` returns None for NOMINAL — doesn't reach `store_event`. Test the invariant. |
| Comment drift if reviewer modifies D3 block without updating comment | LOW | MEDIUM | Comment describes pipeline; if step removed, comment is wrong. Proposed bug class: "Pipeline comment drift". |

---

## Out of Scope (Filed for Future Cycles)

- v4.6.10 HIGH (3 PredictedCost MONETARY sensors) — separate hotfix or v4.6.12
- v4.6.10 MEDIUM (setup duration capture window too narrow) — v4.6.12
- D3 person_seed_helpers extraction — v4.6.12
- D4.7 safety detector ppm fields — v4.6.13 Cycle B (per dashboard backlog)
- Battery/grid power config keys for source_breakdown — v4.6.13
- Subagent protocol fixes (ura-planner Write tool, validator stash methodology) — separate micro-cycle
- NM push-notification channel for CM self-instrumentation anomalies — v4.7+

---

## Review Focus Areas (2 Reviewers, Different Framings)

### Reviewer A — "Correctness + Bug Class Hits"
- D1 `store_event` payload shape matches post-v4.6.7 `anomaly_log` schema
- D1 `save_baselines` ALWAYS called (not only when anomaly returned)
- D1 severity mapping via `map_diag_severity` correct per v4.6.6 vocabulary
- D2.3 `dt_util` module-top import added to coordinator_diagnostics.py
- D4 attribute computations — None handling at every boundary
- D4.8 safety query `auto_dismiss` keyword matches activity_logger emit strings (grep safety.py)
- Bug class touchpoints: #8, #19, #21, #22, #26, #36

### Reviewer B — "Lifecycle + Race + Async + Restart Resilience"
- D1 `load_baselines` startup sequence trace — database before async_start
- D1 background task tracking via `entry.async_create_background_task` preserved
- D1 simulated-restart test creates SECOND detector instance (proves persistence, not state-sharing)
- D1 `store_event` awaited (no fire-and-forget on save_anomaly_event)
- D2.2 `asyncio.run` rewrite — no shared-loop assumptions
- D4.8 cache reset on entity remove (Bug Class #36)
- D4.4 person_tracking_coordinator key + None-paths
- D4.6 get_state_snapshot safe during native_value resolution
- Restart drill: tag, branch, restart twice — verify `metric_baselines` row appears with sample_count incrementing

---

## Ship Plan

1. Branch: `git checkout -b feature/v4.6.11-d3-persistence-and-attrs`
2. Capture baseline counts (Gate 3)
3. Build phases sequential:
   - Phase 1: D1 (manager → __init__.py → tests)
   - Phase 2: D2 (datetime + asyncio cleanup)
   - Phase 3: D4 (manager → aggregation → binary_sensor → sensor → hvac)
4. Tag baseline: `git tag pre-review-v4.6.11`
5. Parallel review: 2 × `ura-reviewer` per framings above
6. Fix CRITICAL + HIGH; re-run tests
7. Pre-deploy snapshot: `SELECT * FROM metric_baselines;` — record current rows
8. Deploy: `./scripts/deploy.sh 4.6.11 ...`
9. Live validation per criteria above
10. Post-review doc: `docs/reviews/code-review/v4.6.11_d3_persistence_and_dashboard_attrs.md`
11. Plan-completion tracking: document deferred items explicitly
