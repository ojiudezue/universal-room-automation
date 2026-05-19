# v4.6.10 — Setup Telemetry + Anomaly Wiring + Deferred Polish

**Date:** 2026-05-18 CDT
**Tier:** Tier 2 (two parallel reviews + validator)
**Predecessor:** v4.6.9 (Boot-State Robustness)

## Why

Three threads bundled:
1. **User wanted a smoke signal on URA setup time** so future regressions surface as a passive trip-wire rather than requiring manual vigilance. The right architecture flexes the anomaly subsystem (v4.6.5/v4.6.6) against URA itself.
2. **HA recorder warnings on v4.6.8 cost sensors** — MONETARY + TOTAL_INCREASING/MEASUREMENT is rejected; needed cleanup.
3. **v4.6.9 review carryovers** — three small deferred items, time to fold them in.

This cycle is also the **first dogfood test of the new subagent enforcement protocol** (memory + CLAUDE.md + slash commands). All four cycle phases routed to URA agents:
- `ura-planner` wrote the plan
- `ura-builder` (now opus-4-7) built D1–D7
- `ura-validator` ran baseline-failure-count comparison (GREEN)
- 2× `ura-reviewer` in parallel with different framings (Tier 2 ceremony)

## What you'll notice

- **New diagnostic sensor:** `sensor.ura_setup_duration_seconds` on the URA: Coordinator Manager device. Shows last boot's setup time. Attributes include `started_at`, `completed_at`, `coordinator_count`, `room_count` — useful context for trend analysis via HA history graph.
- **Zero HA recorder warnings** for MONETARY sensors. Pre-v4.6.10 the cost-today + cost-per-hour sensors logged "state class ... impossible considering device class ('monetary')" warnings on every restart.

## What v4.6.10 does NOT do (read this)

**D3 setup-duration anomaly detection is scaffold-only this cycle.** The observation push + sensor wiring ship, but the AnomalyDetector baseline is in-memory and resets every HA restart — so `minimum_samples=10` is unreachable and anomalies will not fire. The Tier 2 reviewer pair convergently flagged this via different framings; deferred to v4.6.11 with a proper baseline-persistence design.

Code comment + log message updated to say "scaffold-only, no dispatch" so future readers aren't misled by the partial wiring.

## Changes

### D1 — Boot telemetry capture (`__init__.py`)
- `setup_started = dt_util.utcnow()` at top of `async_setup_entry` (wrapped in try/except → debug)
- `setup_completed = dt_util.utcnow()` after `coordinator_manager.async_start()` returns
- Stash at `hass.data[DOMAIN]["setup_telemetry"]` with 5 keys (started, completed, duration_seconds, coordinator_count, room_count)
- Module-top `from homeassistant.util import dt as dt_util` (no function-local re-imports)
- Cleaned up on `async_unload_entry` (B2 review fix — prevents stale data after a failed reload)

### D2 — `URASetupDurationSensor` (`sensor.py`)
- `sensor.ura_setup_duration_seconds`
- `DURATION` device class, `MEASUREMENT` state class, unit `"s"`
- `entity_category = DIAGNOSTIC`, `entity_registry_enabled_default = True`
- Attached to CM device via `_cm_device_info()` helper (overriding AggregationEntity's default integration-device attachment)
- Returns None (not 0.0) when `duration_seconds` key is missing — honors "None when unknown" contract

### D3 — Anomaly observation wiring (scaffold only)
- New `CoordinatorManager._setup_anomaly_detector` (AnomalyDetector instance, `metric_names=["setup_duration_seconds"]`, `minimum_samples=10`)
- Background task pushes one observation per boot via `entry.async_create_background_task` (Bug Class #19)
- Inner + outer try/except blocks both log at `_LOGGER.debug` — telemetry never blocks setup
- **v4.6.11 will add baseline persistence + `store_event` dispatch** to make this functional

### D5a — `_PERSON_LAST_STATE_SKIP_VALUES` module constant (`aggregation.py`)
- Promoted from inline locals in both `PersonPreviousLocationSensor` + `PersonPreviousSeenSensor` `async_added_to_hass`
- `frozenset[str]` — single allocation, immutable

### D5b — Docstring typo (`person_coordinator.py`)
- Both seed-method docstrings at lines 1015 + 1047 corrected: `self._data` → `self.data`

### D5c — Seed-helper extraction
- **Deferred** per the planning doc's conditional rule. Seed helpers reference `self.data` so a pure free-function extraction would require coupling the new module to coordinator state. Not clean enough this cycle. Filed for v4.6.11.

### D6 — HA state-class warning fixes
| Sensor | Before | After |
|---|---|---|
| `WholeHouseCostTodaySensor` (aggregation.py) | TOTAL_INCREASING | TOTAL |
| `ZoneEnergyCostTodaySensor` (aggregation.py) | TOTAL_INCREASING | TOTAL |
| `ZoneCostPerHourSensor` (aggregation.py) | MEASUREMENT | (removed — no state_class for rates) |
| `EnergyPredictedBillSensor` (sensor.py) | MEASUREMENT | (removed) |
| `EnergyArbitrageSavingsTotalSensor` (sensor.py) | TOTAL_INCREASING | TOTAL |

`EnergyImportTodaySensor` was flagged by the user but is ENERGY device class (not MONETARY) — ENERGY + MEASUREMENT is valid. No change needed.

### D7 — Subagent enforcement (shipped pre-cycle)
Memory feedback entries + CLAUDE.md "Subagent Usage Protocol" + slash commands at `.claude/commands/ura-{plan,build,validate,review}.md` were committed before D1 started. First cycle to use the protocol end-to-end.

## Files changed (cycle total + review fixes)

| File | LoC |
|---|---|
| `custom_components/universal_room_automation/__init__.py` | +88 (D1, D3) + review fixes |
| `custom_components/universal_room_automation/domain_coordinators/manager.py` | +18 (D3 detector init) |
| `custom_components/universal_room_automation/sensor.py` | +68 (D2 sensor + D6 fixes) + review fixes |
| `custom_components/universal_room_automation/aggregation.py` | +28 (D5a, D6 fixes) |
| `custom_components/universal_room_automation/person_coordinator.py` | +2 (D5b docstring) |
| `quality/tests/test_v4_6_10_setup_telemetry.py` | +880 (38 tests, all pass) |
| `.claude/agents/`, `.claude/commands/`, `CLAUDE.md` | subagent enforcement |
| `docs/planning/PLANNING_v4.6.10_*.md` | +336 (new) |
| `docs/reviews/code-review/v4.6.10_*.md` | +175 (new) |
| `docs/BACKLOG.md` | +35 (v4.6.10 closure + v4.6.11 entry) |

## Tests
- **38 v4.6.10 tests pass** in isolation
- Baseline: 75 failed / 3236 passed / 14 errors at `pre-review-v4.6.10`
- Feature: 57 failed / 3254 passed / 14 errors on HEAD
- Net: **0 new failures, +18 fixed (cycle's own tests), +17 truly new tests**

## Review

Tier 2 — two parallel reviewers with different framings. **PASS WITH FIXES.**

**Convergent CRITICAL finding** (both reviewers, different angles):
- A C1: D3 missing `store_event` call → no DB persistence, no NM dispatch
- B B1: AnomalyDetector `_baselines` is in-memory → resets every restart → `minimum_samples=10` never reached
- **Together:** D3 is permanently inert as shipped. **Deferred to v4.6.11** with explicit "scaffold-only" comments + log message + BACKLOG entry. This is the Tier 2 ceremony working as designed — a single Tier 1 review might have caught one angle but not both.

**HIGH/MEDIUM addressed in `270fd75` review-fix commit:**
- H1 (A): D3 scheduling call wrapped in own try/except (prevents masking as CM-init failure)
- B2 (B): `setup_telemetry` popped on `async_unload_entry` (Bug Class #36)
- A-M1: Module-top `dt_util` import; removed function-local re-imports (Bug Class #34)
- A-M2: D2 sensor returns None (not 0.0) when key missing
- B-M1: Added source-inspection tests for defensive try/except blocks
- B-M2: Test stub `utcnow` returns tz-aware datetime (Bug Class #21 in test code)

Full review doc: `docs/reviews/code-review/v4.6.10_setup_telemetry.md`.

Two new bug classes proposed for `QUALITY_CONTEXT.md`:
- **"Dead code / incomplete wiring"** — partial-pipeline shipments must explicitly comment their non-functional state
- **"Ephemeral Baseline / Phantom Feature"** — in-memory learning state that resets on the event it measures

## Live validation criteria

Post-deploy verify:
- [ ] `sensor.ura_setup_duration_seconds` populates within 1 min, positive float
- [ ] Sensor visible on URA: Coordinator Manager device card; all 4 attributes populated
- [ ] HA log: ZERO `"state class ... impossible considering device class ('monetary')"` warnings
- [ ] HA log: DEBUG-level "setup telemetry captured" entry confirms D1 capture
- [ ] HA log: NO error/warning for "setup anomaly observation" (D3 scaffold ran cleanly)

## Commits

```
270fd75 v4.6.10 review fixes: 2 HIGH + 4 MEDIUM addressed; CRITICAL D3 deferred honestly
e9b289d v4.6.10: Setup Telemetry + Anomaly Wiring + Deferred Polish
ef96157 v4.6.10 planning + subagent enforcement (A+B+C)
7c26745 Subagents: bump to Opus 4.7 (builder/planner/reviewer), pin all models explicitly
```
