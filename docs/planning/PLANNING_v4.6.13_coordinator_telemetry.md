# PLANNING v4.6.13 — Coordinator Telemetry Sensor Set (Dashboard Cycle C)

**Status:** Draft 2026-05-19, awaiting review
**Tier:** Tier 2 (revised UP from Tier 1 — D2/D3 design audit found the brief's importance-proxy approach is unworkable; recommended path is compliance-table-based, which makes D2/D3 multi-table queries with non-trivial blast radius. Not Tier 2-DB because no schema migration is added.)
**Predecessor:** v4.6.12 Cycle B
**Recall hint:** "Resume v4.6.13 — coordinator telemetry"

---

## TL;DR

Five deliverables surfacing per-coordinator decision telemetry to the v5 Diagnostics tab. The `ura_activity_log` table already persists every coordinator decision, so the implementation is sensor classes querying existing tables — no new logging infrastructure.

**Major design pivots from the brief, both backed by source reads:**

1. **D2 (override frequency) cannot use `ura_activity_log.action LIKE 'override%'`** — no such rows exist. The authoritative override signal is `compliance_log.override_detected = 1`, joined to `decision_log.coordinator_id` (database.py:622-695; coordinator_diagnostics.py:640-695).
2. **D3 (success rate) cannot use `importance` as the success proxy** — emitted vocabulary is `{info, notable, critical}` (activity_logger.py:27-31) with no failure signal; every emit represents a successful command, not an outcome. The success-rate metric is fundamentally a *compliance* concept (commanded vs actual). **Plan reframes D3 as a compliance-rate sensor backed by the existing `compliance_log.compliant` column**, reusing the `coordinator_diagnostics.get_compliance_rate()` DAO already in production.

This pivot makes the cycle slightly bigger than the audit's revised 80-100 LoC estimate (~165 LoC prod + ~160 test) but eliminates a "telemetry-quality v5.1 cycle" the audit had filed as follow-up. **No Tier 2-DB schema migration** — we expose existing data through new sensor surfaces only.

**LoC budget:** ~165 prod + ~160 test = ~325 total. Tier 2: two reviewers, no DB schema change.

---

## Pre-read mandate (reviewers must cite)

- `docs/planning/DASHBOARD_v5_sensor_audit.md` Diagnostics tab section
- `docs/planning/DASHBOARD_BACKLOG.md` activity_logger discovery
- `custom_components/universal_room_automation/database.py`:
  - 580-620 (decision_log schema + indexes)
  - 622-695 (compliance_log schema + scope migration)
  - 990-1008 (ura_activity_log schema + indexes)
  - 1665-1738 (log_decision + log_compliance_check DAOs)
  - 4230-4302 (log_activity write + prune)
- `custom_components/universal_room_automation/activity_logger.py` (full file)
- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py:526-695` (compliance + get_compliance_rate + override stats DAOs)
- `custom_components/universal_room_automation/sensor.py`:
  - 162-326 (CM entry sensor registration block)
  - 1496-1581 (existing `LastAutomationActionSensor` — per-room, NOT per-coordinator)
  - 3471-3516 (`CoordinatorSummarySensor` — CM-device sensor template)
  - 7117-7143 (existing `HVACOverrideFrequencySensor` — separate concept, in-memory, no collision)
  - 10289-10495 (`URARecentAnomaliesSensor` — gold-standard template)
  - 10498-10560 (`URASetupDurationSensor` — minimal cached-value sensor)
- `docs/QUALITY_CONTEXT.md` Bug Classes #11 (UTC vs local date), #21 (tz-naive/aware mix), #26 (high-freq DB read), #38 (lost unsubscribe → listener leak)

---

## Concept dictionary (vocabulary lock for reviewers)

| Term | Definition | Source of truth |
|---|---|---|
| **UI coordinator** | One of the 5 dashboard cards: `presence`, `hvac`, `energy`, `safety`, `security` | P6 prototype lines 1839-1893 |
| **Emit-label coordinator** | The string written to `ura_activity_log.coordinator` (and `decision_log.coordinator_id`). Observed set: `room`, `transit`, `presence`, `safety`, `security`, `notification`, `hvac`, `compliance`, `energy`. | grep audit of 14 `activity_logger.log()` call sites |
| **UI→emit mapping** | A constant dict `COORDINATOR_EMIT_LABELS` mapping each UI coordinator to the tuple of emit-labels rolled up under it. Initial mapping below; revisable per UX feedback without schema change. | New, defined in this plan |
| **Decision** | One row in `ura_activity_log` (post-dedup at activity_logger.py:134-162; window = 30s/60s/300s by importance) | activity_logger.py + database.py |
| **Override** | `compliance_log.override_detected = 1` for a row whose joined `decision_log.coordinator_id` matches the UI→emit mapping | database.py:622-639, coordinator_diagnostics.py:381-407 |
| **Success/compliance** | `compliance_log.compliant = 1` (inverse of "deviation from commanded" condition) | database.py:633, coordinator_diagnostics.py:411-470 |

### Initial UI→emit mapping (D1 source of truth)

```python
COORDINATOR_EMIT_LABELS: dict[str, tuple[str, ...]] = {
    "presence": ("presence", "transit", "room"),    # transit + room emits are presence-driven
    "hvac":     ("hvac",),
    "energy":   ("energy",),
    "safety":   ("safety",),
    "security": ("security",),
}
```

**Justification:** `transit` and `room` emit labels (transitions.py:439, automation.py:1215+, coordinator.py:397+) are sourced from room-level occupancy detection — semantically part of the presence subsystem from the user's perspective. Confirm with UX before deploy.

`compliance` and `notification` emit-labels are intentionally NOT mapped to any UI coordinator. They are meta-events — rolling them up would double-count.

The constant lives in `domain_coordinators/coordinator_telemetry_const.py` so adjusting the mapping is a one-file change with no sensor-class touch.

---

## Deliverables — 5 total

### D1 — Per-UI-coordinator decision count sensors (5 sensors, ~40 LoC prod + ~40 LoC test)

**Goal:** Count of decisions per UI coordinator since local midnight. Diagnostics card row: "Decisions today: 89".

**Entity IDs:** `sensor.ura_{coord}_decisions_today` for each of 5.

**Class:** `CoordinatorDecisionsTodaySensor(AggregationEntity, SensorEntity)` parametrized by `ui_coordinator: str`. Instantiated 5x in CM-entry registration.

**Refresh strategy (Bug Class #26 high-freq-DB-read prevention):**
- Subscribe to `SIGNAL_ACTIVITY_LOGGED` (existing in signals.py)
- Cache last-computed value in `self._count_today: int`
- On each signal dispatch: check `payload["coordinator"]` against `COORDINATOR_EMIT_LABELS[ui_coordinator]`; if match → schedule `_async_refresh()` via `hass.add_job(...)`
- In-flight guard via `_refresh_in_flight` / `_refresh_pending` (mirror URARecentAnomaliesSensor)
- Initial load on `async_added_to_hass`: if database in hass.data → run once; else subscribe to `SIGNAL_DATABASE_READY`
- Capture all unsubscribes into `async_on_remove` (Bug Class #38)

**Query (uses `idx_activity_log_coordinator` index):**

```python
# Bug Class #11: midnight is LOCAL — use dt_util.start_of_local_day()
# then convert to UTC isoformat for comparison vs UTC-stored timestamps.
local_midnight = dt_util.start_of_local_day()
cutoff_utc = dt_util.as_utc(local_midnight).isoformat()
labels = COORDINATOR_EMIT_LABELS[self._ui_coordinator]
placeholders = ",".join("?" * len(labels))
async with database._db_read() as db:
    cursor = await db.execute(
        f"SELECT COUNT(*) FROM ura_activity_log "
        f"WHERE coordinator IN ({placeholders}) AND timestamp >= ?",
        (*labels, cutoff_utc),
    )
    row = await cursor.fetchone()
    self._count_today = row[0] if row else 0
```

**Day-rollover handling:** Signal-driven refresh recomputes cutoff naturally on next decision. No additional midnight timer needed.

**Disabled-coordinator handling:** Returns 0 (not None) — documented and tested.

#### Acceptance Criteria D1
- **Test:** counts rows for mapped labels
- **Test:** resets at local midnight
- **Test:** uses `dt_util.start_of_local_day` (Bug Class #11 guard)
- **Test:** disabled coordinator returns 0
- **Test:** signal refresh in-flight guard works
- **Test:** signal filter by emit label (notification emit doesn't trigger refresh)
- **Verify:** 5 entity IDs, DIAGNOSTIC category, enabled by default, on CM device
- **Live:** each sensor shows non-zero integer within ~5 min of HA restart

---

### D2 — Per-UI-coordinator override frequency sensors (5 sensors, ~40 LoC prod + ~40 LoC test)

**Goal:** Count user overrides per UI coordinator over last 24h. Diagnostics: "Override freq: 6 / day".

**Entity IDs:** `sensor.ura_{coord}_override_frequency` — collision-free with existing `sensor.ura_hvac_coordinator_override_frequency` (different unique_id).

**Critical design pivot from brief:** brief assumed `action LIKE 'override%'` rows. **No such rows exist.** Grep audit of all 14 `activity_logger.log()` call sites shows `action` values: `anomaly`, `cover_open`, `cover_close`, `fan_off`, `fan_on`, `chain_trigger`, `light_on/off/dim`, `armed_state_change`, `preset_change`, `pre_arrival`, `load_shed_escalate`, `notification_sent`, `hazard_detected`. None match override pattern.

**Authoritative override source:** `compliance_log.override_detected = 1` joined to `decision_log.coordinator_id` (database.py:622-639; coordinator_diagnostics.py:640-665).

**Query:**

```python
# Bug Class #21: compliance_log.timestamp is tz-NAIVE (database.py:1730
# uses datetime.utcnow().isoformat()). Strip tzinfo from cutoff to match.
cutoff = (dt_util.utcnow() - timedelta(hours=24)).replace(tzinfo=None).isoformat()
async with database._db_read() as db:
    cursor = await db.execute(
        f"""SELECT COUNT(*) FROM compliance_log c
            JOIN decision_log d ON c.decision_id = d.id
            WHERE c.override_detected = 1
              AND d.coordinator_id IN ({placeholders})
              AND c.timestamp >= ?""",
        (*labels, cutoff),
    )
```

**Refresh trigger:** time-based 5-min polling (compliance writes don't dispatch). Bug Class #38: capture unsub into `async_on_remove`.

#### Acceptance Criteria D2
- **Test:** counts compliance_log overrides for mapped labels
- **Test:** excludes non-override rows
- **Test:** 24h rolling window
- **Test:** handles tz-naive compliance timestamps (Bug Class #21)
- **Test:** no unique_id collision with existing `HVACOverrideFrequencySensor`
- **Verify:** 5 entity IDs
- **Live:** on known override event, sensor increments within 5 min

---

### D3 — Per-UI-coordinator compliance rate sensors (5 sensors, ~30 LoC prod + ~50 LoC test)

**Goal:** Show success rate % per UI coordinator. Diagnostics: "Success rate: 98%".

**Critical pivot from brief:** brief proposed path (i) "importance-as-proxy". **Unworkable.** Importance vocabulary is `{info, notable, critical}` (no warning/error). Every emit represents a successful command, not an outcome.

Brief's path (ii) "add `outcome` column" — wrong answer too. URA already has the outcome data in `compliance_log.compliant`, populated by `coordinator_diagnostics._compare_states` (commanded-vs-actual device state).

**Plan: D3 = compliance rate sensor, reusing `get_compliance_rate()`** (coordinator_diagnostics.py:589-630). One sensor per UI coordinator, returns 7-day compliance percentage.

**Entity IDs:** `sensor.ura_{coord}_compliance_rate`

**Critical implementation note — UI→emit mapping mismatch:** `get_compliance_rate(coordinator_id=...)` filters on `decision_log.coordinator_id` — single emit-label. For UI "presence" mapped to `(presence, transit, room)`, single call won't roll up across 3 labels.

**Decision: option (a) loop the DAO 3 times for "presence"**, sum compliant/total, compute rate. Simple, no DAO change. Per-refresh: 7 calls max across 5 sensors × 2 refreshes/hour = 14 queries/hour.

**Refresh:** time-based 30-min interval (compliance rate is slow-moving 7-day metric).

**Edge case — zero decisions in window:** `get_compliance_rate` returns 1.0 when `total == 0`. The sensor MUST NOT display "100%" on fresh install. **Override:** returns `None` (HA renders "unknown"). Surface total count as `extra_state_attributes["decisions_in_window"]`.

#### Acceptance Criteria D3
- **Test:** aggregates across mapped emit labels (presence = 3 labels)
- **Test:** window is 7 days
- **Test:** zero decisions → returns None, attr `decisions_in_window == 0`
- **Test:** cache doesn't thrash DB
- **Verify:** 5 entity IDs, unit %
- **Live:** sensors render 90%+ for active coordinators; safety/security may show None on fresh install

---

### D4 — URA DB size sensor (1 sensor, ~25 LoC prod + ~20 LoC test)

**Goal:** Show URA SQLite DB size in MB. Diagnostics System card: "DB size: 812 MB".

**Entity ID:** `sensor.ura_db_size_mb`

**Implementation:**

```python
async def async_update(self) -> None:
    import time
    now = time.monotonic()
    if now - self._last_query_time < 300:  # 5 min cache
        return
    try:
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            self._size_mb = None
            return
        db_path = database.db_file
        size_bytes = await self.hass.async_add_executor_job(
            os.path.getsize, db_path
        )
        # Include WAL + SHM sidecars
        for suffix in ("-wal", "-shm"):
            try:
                size_bytes += await self.hass.async_add_executor_job(
                    os.path.getsize, db_path + suffix
                )
            except OSError:
                pass
        self._size_mb = round(size_bytes / (1024 * 1024), 2)
        self._last_query_time = now
    except FileNotFoundError:
        self._size_mb = None
    except Exception:
        _LOGGER.debug("URADBSizeSensor: getsize failed", exc_info=True)
```

**Why include WAL/SHM:** URA runs SQLite in WAL mode. The `-wal` file can be 100s of MB during heavy write bursts. User-meaningful "DB size" must include it.

#### Acceptance Criteria D4
- **Test:** returns file size in MB
- **Test:** includes WAL + SHM
- **Test:** missing WAL doesn't fail
- **Test:** DB not initialized → returns None
- **Test:** cache respects 5-min window
- **Verify:** 1 entity ID, unit MB
- **Live:** matches `ls -lh` on actual DB file (+ WAL + SHM)

---

### D5 — Per-UI-coordinator last-decision sensors (5 sensors, ~30 LoC prod + ~30 LoC test)

**Goal:** Per-coord "last decision" timestamp + description. Diagnostics: "Last decision: 18:42 · Master → coast".

**Audit result:** existing `LastAutomationActionSensor` / `LastAutomationTimeSensor` (sensor.py:1496-1581) are **per-room**, NOT per-domain-coordinator. D5 genuinely needed.

**Entity IDs:** `sensor.ura_{coord}_last_decision_time` (5 sensors, not 10 — description in attrs).

**Attributes:** `device_class=TIMESTAMP`, DIAGNOSTIC.

**Query:**

```python
async with database._db_read() as db:
    cursor = await db.execute(
        f"""SELECT timestamp, action, description, room, zone, entity_id
            FROM ura_activity_log
            WHERE coordinator IN ({placeholders})
            ORDER BY timestamp DESC
            LIMIT 1""",
        labels,
    )
    row = await cursor.fetchone()
    if row is None:
        self._last_ts = None
    else:
        # Bug Class #21: ura_activity_log writes are tz-aware via dt_util.
        self._last_ts = dt_util.parse_datetime(row[0])
        self._last_attrs = {
            "action": row[1], "description": row[2],
            "room": row[3], "zone": row[4], "entity_id": row[5],
        }
```

**Refresh trigger:** SIGNAL_ACTIVITY_LOGGED with emit-label filter (same as D1).

#### Acceptance Criteria D5
- **Test:** returns most recent row across mapped labels
- **Test:** no rows → returns None
- **Test:** attrs include action + room
- **Test:** parse_datetime handles tz-aware string
- **Verify:** 5 entity IDs, device_class=TIMESTAMP
- **Live:** matches manual SELECT against ura_activity_log

---

## Files touched

| File | Change | LoC delta |
|---|---|---|
| `domain_coordinators/coordinator_telemetry_const.py` | **NEW.** `COORDINATOR_EMIT_LABELS` dict + sensor constants | +25 |
| `sensor.py` | Add 5 new sensor classes + 21 instantiations | +140 |
| `quality/tests/test_v4_6_13_coordinator_telemetry.py` | **NEW.** Behavioral tests against real schema (Bug Class #39) | +160 |
| `docs/readmes/README_v4.6.13.md` | **NEW.** Release notes | +50 |

**Total prod:** ~165 LoC. **Total test:** ~160 LoC.

**Files explicitly NOT touched:**
- `database.py` — no schema migration, no new DAOs
- `activity_logger.py` — no changes to emit shape, dedup, or signal
- `coordinator_diagnostics.py` — `get_compliance_rate` called as-is
- `signals.py` — no new signals (D2 uses polling)

---

## Sensor performance budget

15 new diagnostic sensors. Worst-case query rate:

- **D1 (5 sensors):** Signal-driven, dedup'd by emit-label filter. ~50 decisions/hour observed in v4.6.7 production → 10 refreshes/sensor/hour. **Total: 50 queries/hour.**
- **D2 (5 sensors):** 5-min polling. **Total: 60 queries/hour.**
- **D3 (5 sensors):** 30-min polling. Option (a) loop = 7 calls × 2/hr = **14 queries/hour.**
- **D4 (1 sensor):** 5-min polling, no DB query (filesystem). **12 stat() calls/hour.**
- **D5 (5 sensors):** Signal-driven, same volume as D1. **Total: 50 queries/hour.**

**Aggregate: ~174 DB queries/hour**, all hitting indexed `_db_read()` (WAL-mode concurrent reads). Negligible vs existing workload.

Reviewer B: run `EXPLAIN QUERY PLAN` on each query; assert index usage (`idx_activity_log_coordinator` for D1/D5; `idx_decision_coordinator` for D2/D3 join).

---

## Risk register

| Risk | Severity | Mitigation | Owner |
|---|---|---|---|
| UI→emit mapping is wrong | MEDIUM | Mapping is single dict in `coordinator_telemetry_const.py`; revisable in hotfix. Pre-deploy: ask UX. | Planner |
| `compliance_log.timestamp` tz-naive vs `ura_activity_log` tz-aware (Bug Class #21) | HIGH | D2 query strips tzinfo on cutoff. D5 uses `dt_util.parse_datetime` on read. Tests assert both shapes work. | Reviewer A |
| D1 signal-refresh storms during boot replay | MEDIUM | In-flight guard + `_refresh_pending` (mirrors URARecentAnomaliesSensor v4.6.3 fix). | Reviewer B |
| D3 reports misleading "100%" on fresh install with zero decisions | MEDIUM | Sensor returns `None` when total=0; total in attrs. | Planner |
| D4 reports stale size during heavy WAL activity | LOW | 5-min cache + WAL/SHM inclusion. | Planner |
| Sensor count proliferation — 21 new entities on CM device | LOW | All DIAGNOSTIC; user can disable individually. Per audit, dashboard needs them. | Planner |
| Race: `database` not yet in hass.data at sensor setup | HIGH | Reuse SIGNAL_DATABASE_READY pattern from URARecentAnomaliesSensor (sensor.py:10370-10390). Mandatory in `async_added_to_hass`. | Reviewer A+B |
| Missing `async_on_remove` for time-interval cancellers (Bug Class #38) | MEDIUM | Each polling sensor MUST capture unsub from `async_track_time_interval` and `async_on_remove(unsub)`. Tests verify cleanup. | Reviewer A |
| Existing `HVACOverrideFrequencySensor` vs new `ura_hvac_override_frequency` | MEDIUM | Different unique_ids verified. Document both; filed v5.1 consolidation. | Planner |
| `get_compliance_rate` returns 1.0 (not None) when no rows — masks fresh-install state | HIGH | D3 in-sensor check parallel SELECT COUNT(*) to gate None-return. | Reviewer A |

---

## Out of scope (file for v5.1+)

- Meta-anomalies on telemetry ("Decisions today dropped to 0 — coordinator stuck?")
- Per-coordinator latency tracking (P50/P95 of decision_log execution duration)
- Success rate trending (7d-on-7d delta)
- `SIGNAL_COMPLIANCE_RECORDED` dispatcher for sub-minute override-rate updates
- `get_compliance_rate(coordinator_ids=[...])` API widening
- Midnight reset timer for D1 — defer; signal-driven refresh acceptable
- Consolidation of new `ura_hvac_override_frequency` with existing — v5.1 after dashboard validates

---

## Review tier — Tier 2 (two reviewers)

**Why not Tier 1:** D2 + D3 cross multiple tables (`ura_activity_log` AND `compliance_log` AND `decision_log`) and reuse a stable DAO whose contract (returning 1.0 for empty) is a foot-gun.

**Why not Tier 2-DB:** No schema migration. No DAO definition changes. No payload-shape changes.

**Review A framing — sensor correctness + concurrency:**
- Each sensor's `_async_refresh` idempotent under burst-fire
- In-flight guard + pending-queue matches URARecentAnomaliesSensor
- All unsubscribes captured into `async_on_remove` (Bug Class #38)
- All datetime parses use `dt_util.parse_datetime` (Bug Class #21)
- D3 None-on-zero contract holds
- UI→emit mapping correct per UX intent

**Review B framing — DB load + query correctness:**
- `EXPLAIN QUERY PLAN` confirms index usage
- Compliance_log tz-naive cutoff matches stored shape
- Cache windows honored on error path (no log spam)
- `_db_read()` connections close under exception
- No new query creates sequential scan on tables >100k rows

---

## Pre-deploy checklist

- [ ] Pre-stage `domain_coordinators/coordinator_telemetry_const.py` + new test file with `git add` before deploy.sh
- [ ] `docs/readmes/README_v4.6.13.md` written
- [ ] PRE-REVIEW tag set
- [ ] Verify `ura-sqlite` MCP `--db-path` points to live DB
- [ ] Snapshot pre-deploy row counts: `SELECT coordinator, COUNT(*) FROM ura_activity_log WHERE timestamp >= date('now') GROUP BY coordinator;`

---

## Plan completion tracking

After implementation, document in `docs/reviews/code-review/v4.6.13_coordinator_telemetry.md`:
- Whether UI→emit mapping shipped as planned or adjusted
- Whether D3 option (a) loop kept or pivoted to option (b)
- Whether D4 included WAL/SHM
- Any sensor deferred + tracking
