# PLANNING v4.6.10 — Setup Telemetry + Anomaly Wiring + Deferred Polish

**Status:** Approved 2026-05-18, ready to build
**Tier:** Tier 2 (per user directive 2026-05-18 — bumped from default Tier 1 because this cycle wires the anomaly system + NM into a new diagnostic surface; two-reviewer ceremony to catch race conditions and threat-model gaps)
**Predecessor:** v4.6.9 (Boot-State Robustness — RestoreEntity + coordinator-ready signals)
**Recall hint:** "Resume v4.6.10 — setup telemetry"

---

## TL;DR

Three buckets:

1. **Boot telemetry capture** — `__init__.py` measures `async_setup_entry` start→done duration, stashes in `hass.data[DOMAIN]`, exposes as a CM-device diagnostic sensor (`sensor.ura_setup_duration_seconds`), pushes one observation per boot into the anomaly subsystem. After enough boots, a markedly slower startup fires an anomaly that cascades through the existing AnomalyDetector → NM pipeline (already wired in v4.6.5/v4.6.6).
2. **Deferred polish from v4.6.9 review** — `_SKIP_STATES` module constant, comment typo, optional seed-helpers extraction.
3. **State-class warning cleanup** — fix HA recorder warnings about MONETARY + TOTAL_INCREASING/MEASUREMENT incompatibility on cost sensors.

Plus a note that subagent enforcement (D7) is now live for the first time in this cycle.

---

## Origin

Two threads converged:
- v4.6.9 review carried forward three small polish items (LOW/MEDIUM findings)
- HA logs after v4.6.9 deploy continued to flag MONETARY + state_class incompatibility warnings on the cost sensors shipped in v4.6.8. Per HA dev docs and core issues #86780, #88457, #115692, MONETARY sensors must use `state_class = TOTAL` (or `None`); MEASUREMENT and TOTAL_INCREASING are rejected.
- User asked for a "real future work" deliverable that flexes the anomaly system in a new direction (URA self-instrumentation), dogfooding the v4.6.5/v4.6.6 detector → NM cascade against URA itself.

---

## Deliverables — 7 total

### D1 — Boot telemetry capture (`__init__.py`)

**Goal:** Measure how long URA's `async_setup_entry` takes end-to-end for the integration entry's domain-coordinator init block, with zero risk of blocking setup.

**Capture points (integration-entry path only, `entry_type == ENTRY_TYPE_INTEGRATION`):**
- `setup_started = dt_util.utcnow()` — top of `async_setup_entry` (~line 595), wrapped in try/except + `_LOGGER.debug` on failure. Bug Class #21: use `dt_util`, not raw `datetime`.
- `setup_completed = dt_util.utcnow()` — immediately after `await coordinator_manager.async_start()` returns (`__init__.py:~2006`), before `hass.data[DOMAIN]["coordinator_manager"] = coordinator_manager` is set.

**Stash location:**
```python
hass.data[DOMAIN]["setup_telemetry"] = {
    "started":            <datetime>,   # UTC, tz-aware
    "completed":          <datetime>,   # UTC, tz-aware
    "duration_seconds":   (completed - started).total_seconds(),
    "coordinator_count":  len(coordinator_manager.coordinators),
    "room_count":         <count of ENTRY_TYPE_ROOM entries>,
}
```

**Hardening rules:**
- All telemetry code wrapped in a single `try/except Exception` block logging at `_LOGGER.debug`. Never raises into setup.
- Telemetry write is the LAST thing in the CM init block. If it fails, integration is fully functional; only the sensor + anomaly observation are missing for that boot.

**LoC budget:** ~30 prod + ~30 test.

#### Acceptance Criteria D1
- **Test:** `test_setup_telemetry_populated_on_success` — patch `dt_util.utcnow` to return controlled instants, call `async_setup_entry`, assert `hass.data[DOMAIN]["setup_telemetry"]` has all 5 keys, `duration_seconds` matches the controlled delta within float tolerance.
- **Test:** `test_setup_telemetry_does_not_block_setup_on_dt_failure` — patch `dt_util.utcnow` to raise on first call; assert `async_setup_entry` still returns `True` and `setup_telemetry` is absent (not None-poisoned).
- **Test:** `test_setup_telemetry_coordinator_and_room_counts_accurate` — register two room entries + a CM stub, assert counts match.
- **Verify:** `setup_telemetry` is keyed by stable strings (no dict mutation through the cycle).
- **Live (post-restart):** Watch HA logs at `_LOGGER.debug` level — confirm "setup telemetry captured" line appears.

---

### D2 — `URASetupDurationSensor` diagnostic sensor

**Goal:** Surface the captured duration as a per-boot diagnostic sensor on the Coordinator Manager device. User sees "URA took 12.4s to set up" and HA's history graph shows the trend.

**Decision:** Place in `aggregation.py` alongside existing CM-aggregation sensors. Avoids a new platform registration in `__init__.py`.

**Class shape:**
```python
class URASetupDurationSensor(AggregationEntity, SensorEntity):
    """Diagnostic sensor: URA setup_entry duration (last boot)."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_icon = "mdi:timer-outline"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_setup_duration_seconds"
        self._attr_name = "URA Setup Duration"

    @property
    def native_value(self) -> float | None:
        telem = self.hass.data.get(DOMAIN, {}).get("setup_telemetry")
        if not telem:
            return None
        return round(float(telem.get("duration_seconds", 0)), 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        telem = self.hass.data.get(DOMAIN, {}).get("setup_telemetry") or {}
        return {
            "started_at":        telem.get("started"),
            "completed_at":      telem.get("completed"),
            "coordinator_count": telem.get("coordinator_count"),
            "room_count":        telem.get("room_count"),
        }
```

**Device attachment:** Build cycle must verify whether `AggregationEntity.device_info` attaches to the integration entry device or the CM device. If integration entry, override `device_info` to return CM device identifiers (`{(DOMAIN, "coordinator_manager")}`).

**LoC budget:** ~30 prod + ~25 test.

#### Acceptance Criteria D2
- **Test:** `test_setup_duration_sensor_reads_from_hass_data` — pre-populate `hass.data[DOMAIN]["setup_telemetry"]`, assert `native_value` returns rounded duration and attributes match.
- **Test:** `test_setup_duration_sensor_none_when_telemetry_missing` — empty `hass.data[DOMAIN]`, assert `native_value` is None (not 0, not raise).
- **Test:** `test_setup_duration_sensor_unique_id_stable` — instantiate twice, assert same `unique_id`.
- **Verify:** `entity_registry_enabled_default = True`.
- **Verify:** `device_info` returns CM device identifiers, not integration device.
- **Sensor:** `sensor.ura_setup_duration_seconds` shows a positive float within first minute of HA restart.
- **Live (post-restart):** Appears on URA: Coordinator Manager device card; value > 0; all four attributes populated.

---

### D3 — AnomalyDetector observation wiring for `setup_duration_seconds`

**STATUS POST-REVIEW:** Scaffold-only in v4.6.10. Tier 2 reviewers (A C1 + B B1) independently flagged that `AnomalyDetector._baselines` is purely in-memory and resets every restart. Since `setup_duration_seconds` accumulates ONE observation per boot, `minimum_samples=10` will NEVER be reached. The observation push + sensor wiring ships in v4.6.10 as scaffolding; the persistence layer (baseline → DB) + `AnomalyEvent` construction + `store_event` call for NM dispatch ship in **v4.6.11** (filed in BACKLOG.md). Code comment + log message updated to reflect "scaffold-only, no dispatch" so future readers aren't misled.

**Goal (scaffolding only this cycle):** Wire the observation pipeline so the v4.6.11 follow-up only adds persistence + dispatch, not the data path.

**Context verified via `domain_coordinators/manager.py` + `domain_coordinators/base.py`:**
- `BaseCoordinator.anomaly_detector` is None by default; each domain coordinator instantiates its own.
- `CoordinatorManager` does NOT currently have an `anomaly_detector` — it's not a `BaseCoordinator` subclass.
- **Decision:** Add a CM-level `AnomalyDetector` instance as `coordinator_manager._setup_anomaly_detector`. Cleanest scope — `setup_duration_seconds` is a CM-scope metric.

**Implementation in `manager.py`:**
```python
from .coordinator_diagnostics import AnomalyDetector
self._setup_anomaly_detector = AnomalyDetector(
    hass=hass,
    coordinator_id="coordinator_manager",
    metric_names=["setup_duration_seconds"],
    minimum_samples=10,  # mature baseline after ~10 boots
)
```

**Observation push in `__init__.py`** (after CM in `hass.data[DOMAIN]`):
- Use `entry.async_create_background_task` (Bug Class #19)
- Wrap inner body in try/except with `_LOGGER.debug` on failure
- Call `cm.setup_anomaly_detector.record_observation(metric_name="setup_duration_seconds", scope="house", value=duration_s)`
- If a returned anomaly is non-None, log at info; let existing AnomalyDetector → NM cascade handle dispatch

**Open question for build cycle (NO FABRICATION):**
- `AnomalyDetector.record_observation` at `coordinator_diagnostics.py:803-843` only updates in-memory baseline + appends to `_active_anomalies`. Whether the NM cascade fires automatically from this call OR requires separate persistence/dispatch wiring is unverified. Build agent MUST trace an existing detector's metric end-to-end (e.g., safety's detection) before claiming the cascade is automatic. If a separate dispatch is needed, add it; budget grows by ~10 prod + ~20 test LoC.

**LoC budget:** ~25 prod + ~40 test (default); ~35 prod + ~60 test if explicit NM dispatch wiring needed.

#### Acceptance Criteria D3
- **Test:** `test_setup_anomaly_observation_pushed_against_mocked_detector` — mock CM with mock `setup_anomaly_detector.record_observation`, run setup, await bg task, assert called once with expected args.
- **Test:** `test_setup_observation_failure_does_not_crash_setup` — mock to raise; assert bg task swallows at debug, setup returns True.
- **Test:** `test_setup_observation_when_cm_missing` — CM absent from `hass.data`, no exception, no observation.
- **Test:** `test_setup_observation_no_double_push_on_reload` — reload entry, exactly one observation per setup invocation.
- **Test:** `test_setup_anomaly_detector_registered_on_cm_init` — instantiate CM, assert detector present with correct metric + minimum_samples.
- **Live (post-restart):** First 10 boots do NOT fire anomaly (baseline immature). After ~10+ boots an outlier fires.
- **Live (DB):** Query `metric_observations` for `metric_name='setup_duration_seconds'` + `coordinator_id='coordinator_manager'`. Build cycle verifies whether `record_observation` persists or only updates in-memory; adjusts Live check accordingly.

---

### D4 — Tier 2 review focus: threat-model honor

**Design rule:** Telemetry is observational only. Setup MUST NOT depend on it for any logic.

**Reviewer pair MUST verify:**
1. Every telemetry call path wrapped in try/except → `_LOGGER.debug` (NOT error/warning).
2. `setup_telemetry` dict absence handled at every read site (D2 sensor returns None; D3 push gracefully no-ops).
3. Background task in D3 has its OWN inner try/except — outer `async_create_background_task` is not sufficient; exceptions in coroutines log at error.
4. CM-level `_setup_anomaly_detector` instantiation wrapped so detector failure does NOT prevent CM construction. CM failing = URA dead.

**Smoke test required:**
```python
def test_setup_completes_even_when_all_telemetry_raises(hass, mock_entry):
    """D4: force every telemetry call to raise; setup still returns True."""
    with patch("custom_components.universal_room_automation.dt_util.utcnow",
               side_effect=RuntimeError("simulated dt failure")):
        result = await async_setup_entry(hass, mock_entry)
        assert result is True
        assert "setup_telemetry" not in hass.data.get(DOMAIN, {})
```

#### Acceptance Criteria D4
- **Test:** `test_setup_completes_even_when_all_telemetry_raises` passes.
- **Test:** `test_setup_completes_even_when_anomaly_detector_init_raises` — patch `AnomalyDetector.__init__` to raise; CM still constructs, integration still sets up.
- **Test:** `test_setup_completes_even_when_record_observation_raises`.
- **Verify (review checklist):** Reviewer pair signs off explicitly on the "telemetry never blocks setup" rule in their review docs.

---

### D5 — Deferred v4.6.9 polish

**D5a — `_SKIP_STATES` module-level constant (`aggregation.py`):**
Currently inlined in `PersonPreviousLocationSensor.async_added_to_hass` (~line 4366) and `PersonPreviousSeenSensor.async_added_to_hass` (~line 4450). Promote to module-top as `_PERSON_LAST_STATE_SKIP_VALUES: frozenset[str]`. Replace both inline definitions.

**D5b — Comment typo (`person_coordinator.py`):**
Docstrings at lines 1015 + 1047 say `self._data`; actual attribute is `self.data` (DataUpdateCoordinator). Fix both.

**D5c — Seed-helper extraction (CONDITIONAL):**
Extract `seed_previous_location` + `seed_previous_location_time` to `domain_coordinators/person_seed_helpers.py` (no `homeassistant.components.person` import) so tests can import directly.

**Conditional rule:** Ship D5c ONLY if extraction is clean — helpers operate on a dict-like state argument, no other `self` state. Default to deferral if any doubt → log in BACKLOG for v4.6.11.

**LoC budget:** ~10 prod (D5a + D5b) + 0–30 prod (D5c) + 0–20 test (D5c).

#### Acceptance Criteria D5
- **Verify (D5a):** Grep `_SKIP_STATES = {` returns zero; `_PERSON_LAST_STATE_SKIP_VALUES` appears once at module top + two use sites.
- **Verify (D5b):** Grep `self._data` in `person_coordinator.py` seed-method docstrings returns zero.
- **Test (D5a):** Existing v4.6.9 tests for `PersonPreviousLocation/Seen` continue to pass.
- **Test (D5c, if shipped):** Free-function helper called with synthetic dict shows idempotent behavior.
- **Live:** No user-visible change (refactor only).

---

### D6 — HA state-class warning fixes

**Goal:** Eliminate HA recorder warnings of the form `"Entity ... is using state class '...' which is impossible considering device class ('monetary')..."`.

**Background:** MONETARY device class is incompatible with MEASUREMENT and TOTAL_INCREASING. Accepted patterns: `TOTAL` (with `last_reset` for daily-resetting accumulators) or no `state_class` at all (for rate-of-change values).

**Affected sensors (verified by source read 2026-05-18):**

| Sensor | File:Line | Current | Target |
|---|---|---|---|
| `WholeHouseCostTodaySensor` | `aggregation.py:~2200` | `TOTAL_INCREASING` | `TOTAL` |
| `ZoneEnergyCostTodaySensor` | `aggregation.py:~3386` | `TOTAL_INCREASING` | `TOTAL` |
| `ZoneCostPerHourSensor` | `aggregation.py:~3430` | `MEASUREMENT` | `None` (delete state_class line) |

**Pre-existing EC sensors:** Build cycle MUST extract the exact entity IDs from HA log entries before editing. Do NOT fabricate. Build agent: grep `MONETARY` in `custom_components/universal_room_automation/` and review each result's `state_class` against the rule above. Three pre-existing EC sensors were flagged in HA logs after v4.6.8 deploy:
- `sensor.ura_energy_coordinator_predicted_bill`
- `sensor.ura_energy_coordinator_arbitrage_savings_total`
- `sensor.ura_energy_coordinator_energy_import_today` (this one is ENERGY, not MONETARY — different rule)

**LoC budget:** ~10 prod (attribute edits only).

#### Acceptance Criteria D6
- **Verify:** Grep `state_class.*MONETARY|MONETARY.*state_class`; every MONETARY sensor is `TOTAL` or no state_class.
- **Verify:** HA log after restart shows ZERO `"state class ... impossible considering device class ('monetary')"` warnings for affected sensors.
- **Verify:** `sensor.universal_room_automation_whole_house_cost_today` continues to reset daily after change. Build cycle: patch `WholeHouseEnergy.native_value` low → assert cost drops within one update cycle.
- **Test:** `test_monetary_sensors_use_total_state_class` — instantiate each affected sensor, assert `_attr_state_class in (SensorStateClass.TOTAL, None)`.
- **Live (post-restart):** Filter HA log for "monetary" / "state class" — zero warnings within 10 min of startup.
- **Live (post-restart):** Whole House Cost Today shows positive value within first energy update cycle; Zone Cost Per Hour shows positive USD/h when power draw > 0.

---

### D7 — Subagent enforcement (shipped pre-cycle — note only)

Memory + CLAUDE.md + slash commands at `.claude/commands/ura-{plan,build,validate,review}.md` are already in place. **No code work in D7.**

v4.6.10 is the first dogfood test. Plan → `ura-planner`; build → `ura-builder`; reviews (Tier 2 = two parallel) → `ura-reviewer`; validation → `ura-validator`. If any phase falls back to `general-purpose`, the protocol regressed — file v4.6.11 hotfix.

#### Acceptance Criteria D7
- **Verify:** All four cycle phases performed by their designated URA subagent.
- **Verify:** If any phase falls back to `general-purpose`, noted in post-deploy retro for v4.6.11.

---

## Constraints (apply across all deliverables)

- **Bug Class #21:** Use `dt_util.now()` / `dt_util.utcnow()` exclusively.
- **Bug Class #19:** Use `entry.async_create_background_task` for the AnomalyDetector observation push.
- **Module-top imports preferred.** Function-local imports only where circular dependency forces it (precedent: `__init__.py:1137` imports `SIGNAL_BAYESIAN_READY` locally).
- **All threat-model try/except wraps logged at `_LOGGER.debug`**, not error/warning. Non-fatal degradations.
- **NO soak watching.** Live validation is post-restart only; no 24-hour wait gates.
- **No back-compat scaffolding** (single-install per `project_single_user_no_backcompat`).
- **No fabrication.** Build cycle MUST read existing AnomalyDetector → NM dispatch chain end-to-end before declaring D3's cascade complete.

---

## LoC budget summary

| Deliverable | Prod LoC | Test LoC |
|---|---|---|
| D1 (telemetry capture) | ~30 | ~30 |
| D2 (sensor) | ~30 | ~25 |
| D3 (anomaly wiring) | ~25 | ~40 (+10/+20 if explicit NM dispatch needed) |
| D4 (threat-model tests) | 0 | ~30 |
| D5a + D5b (polish) | ~10 | 0 |
| D5c (seed extraction, conditional) | 0 or ~30 | 0 or ~20 |
| D6 (state-class fixes) | ~10 | ~10 |
| D7 (subagent — note only) | 0 | 0 |
| **TOTAL (default)** | **~105** | **~135** |
| **TOTAL (worst case)** | **~145** | **~175** |

---

## Files touched

| File | Deliverable(s) |
|---|---|
| `custom_components/universal_room_automation/__init__.py` | D1, D3 |
| `custom_components/universal_room_automation/aggregation.py` | D2, D5a, D6 |
| `custom_components/universal_room_automation/person_coordinator.py` | D5b, possibly D5c |
| `custom_components/universal_room_automation/domain_coordinators/manager.py` | D3 |
| `custom_components/universal_room_automation/domain_coordinators/person_seed_helpers.py` | D5c (NEW, conditional) |
| EC files (TBD by log audit) | D6 (up to 3 sensor classes) |
| `quality/tests/test_v4_6_10_setup_telemetry.py` | D1, D2, D3, D4, D6 (NEW) |

---

## Out of scope (explicit)

- `ura-deployer` agent deletion — separate cleanup ticket.
- Per-metric z-threshold customization — still deferred per existing trigger conditions.
- Anomaly-on-anomaly meta — defer until baseline exists (10+ boots).
- Multi-boot trend visualization (HA history UI is sufficient).
- Persistence of `setup_telemetry` across HA restarts — explicit non-goal; each boot's value stands alone. Baseline accumulates via detector's persistence path.
- Fixing `coordinator_diagnostics.py:798`'s `datetime.utcnow()` Bug Class #21 violation — discovered during reads, deferred to v4.6.11.

---

## Verification checklist (cycle close)

- [ ] All 7 deliverables shipped or explicitly deferred with reason
- [ ] Tier 2: two independent staff-engineer reviews completed (Review A correctness/D1/D2/D3/D6; Review B race/lifecycle/threat-model/D4)
- [ ] Post-review doc at `docs/reviews/code-review/v4.6.10_setup_telemetry.md`
- [ ] Live validation post-restart: D1 telemetry stash exists, D2 sensor positive, D3 background task ran without error, D6 no MONETARY warnings
- [ ] Pre-deploy: `git tag pre-review-v4.6.10` set before review fixes
- [ ] HACS install verification: `installed_version == 4.6.10` after deploy.sh + restart

---

## Key gaps the build cycle MUST resolve (no fabrication)

1. **D3 NM cascade trace:** `AnomalyDetector.record_observation` only updates in-memory baseline. Whether NM dispatch is automatic via wrapper / poll OR needs explicit call is unverified. Trace end-to-end before claiming complete.
2. **D2 device attachment:** Confirm `AggregationEntity.device_info` attaches to CM device, or override.
3. **D6 EC sensor list:** Read live HA logs for MONETARY warnings before changing files.

---

## Recall hint

"Resume v4.6.10 — setup telemetry. D1=capture, D2=sensor, D3=anomaly push, D4=threat-model tests, D5=v4.6.9 polish, D6=MONETARY state-class fixes, D7=subagent dogfood."
