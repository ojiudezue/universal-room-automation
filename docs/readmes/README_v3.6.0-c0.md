# Universal Room Automation v3.6.0-c0 — Domain Coordinator Base Infrastructure

**Release Date:** 2026-02-26
**Internal Reference:** C0 (Domain Coordinators — Base Infrastructure)
**Previous Release:** v3.5.3
**Minimum HA Version:** 2024.1+
**Depends on:** v3.5.3

---

## Summary

v3.6.0-c0 delivers the foundational framework for domain coordinators — a tiered, priority-based system where specialized coordinators (Safety, Security, Energy, HVAC, Comfort) evaluate triggers and propose actions that are conflict-resolved before execution. This cycle builds the base classes, manager, conflict resolver, house state machine, signal system, database logging, config flow toggle, and diagnostic sensors. No concrete coordinator implementations yet — those come in subsequent cycles (C1+).

### What's New

- **BaseCoordinator ABC** — Abstract base class with `async_setup()`, `evaluate()`, `async_teardown()` lifecycle, priority attribute, and device info integration
- **CoordinatorManager** — Intent queue with 100ms batching window, priority-ordered coordinator evaluation, conflict resolution, action execution, and decision logging
- **ConflictResolver** — Groups proposed actions by target device, picks winner by `coordinator.priority * severity_factor * confidence`
- **HouseStateMachine** — 9-state FSM (AWAY, ARRIVING, HOME_DAY, HOME_EVENING, HOME_NIGHT, SLEEP, WAKING, GUEST, VACATION) with valid transition enforcement, per-state hysteresis (minimum dwell time), manual override, and force-state for emergencies
- **Intent/Action Models** — `Intent` (trigger event), `CoordinatorAction` (base), `ServiceCallAction`, `NotificationAction`, `ConstraintAction` dataclasses with severity levels (LOW/MEDIUM/HIGH/CRITICAL)
- **Signal Constants** — Inter-coordinator dispatcher signals: `house_state_changed`, `energy_constraint`, `comfort_request`, `census_updated`, `safety_hazard` with typed data classes
- **3 New Sensors** — Coordinator Manager Status (diagnostic), House State, Coordinator Summary
- **Database Schema** — `decision_log`, `compliance_log`, `house_state_log` tables with indexes and retention policies (90/90/365 days)
- **Config Flow Toggle** — Enable/disable domain coordinators via integration options menu
- **Device Hierarchy** — Zone Manager parent device for zone sensors; Coordinator Manager parent device for coordinator devices (via `via_device`)

### What Changed

- Zone sensors now grouped under Zone Manager parent device instead of generic integration device
- All new code is Python 3.9+ compatible (StrEnum backport, dataclass field defaults for inheritance)

---

## Architecture Overview

```
Intent (trigger)
    |
    v
CoordinatorManager (100ms batch window)
    |
    v
Coordinators evaluated in priority order:
    Safety (100) > Security (80) > Energy (40) > HVAC (30) > Comfort (20)
    |
    v
Each returns list[CoordinatorAction]
    |
    v
ConflictResolver: group by target_device, pick highest effective_priority
    |
    v
Execute winning actions (service calls, notifications, constraints)
    |
    v
Log decisions to SQLite
```

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `domain_coordinators/__init__.py` | **New** | Package init for domain coordinators sub-package |
| `domain_coordinators/base.py` | **New** | BaseCoordinator ABC, Intent, CoordinatorAction and subclasses, Severity, ActionType |
| `domain_coordinators/house_state.py` | **New** | HouseState enum, HouseStateMachine, valid transitions, hysteresis defaults |
| `domain_coordinators/manager.py` | **New** | CoordinatorManager, ConflictResolver, intent batching, action execution |
| `domain_coordinators/signals.py` | **New** | Signal constants and typed data classes for inter-coordinator communication |
| `__init__.py` | Modified | Zone Manager device registration, CoordinatorManager init/teardown |
| `aggregation.py` | Modified | Zone sensors use `via_device=(DOMAIN, "zone_manager")` |
| `config_flow.py` | Modified | Domain coordinators options toggle, abort reason fix |
| `const.py` | Modified | Added coordinator constants and retention days |
| `database.py` | Modified | 3 new tables + 3 new logging methods |
| `sensor.py` | Modified | 3 new coordinator sensors (conditional on feature toggle) |
| `strings.json` | Modified | UI strings for domain coordinators options step |
| `quality/tests/test_domain_coordinators.py` | **New** | 51 tests covering all new modules |

---

## How to Deploy

### From source (development)

```bash
# Pre-stage subdirectory (deploy.sh glob doesn't capture subdirs)
git add custom_components/universal_room_automation/domain_coordinators/
./scripts/deploy.sh "3.6.0-c0" "C0: Domain coordinator base infrastructure" "<release notes>"
```

### HACS update

After the GitHub release is published, HACS will detect v3.6.0-c0 as an available update. Update through the HACS UI and restart Home Assistant.

### Manual install

1. Download the release zip from GitHub
2. Extract to `custom_components/universal_room_automation/`
3. Restart Home Assistant

---

## How to Verify It Works

### 1. Domain coordinators toggle appears in options

1. Go to **Settings > Devices & Services > Universal Room Automation > Configure**
2. The options menu should include "Domain Coordinators"
3. Toggle it on, save, and restart

### 2. New sensors appear when enabled

1. After enabling domain coordinators and restarting:
   - `sensor.ura_coordinator_manager_status` — shows "idle" (diagnostic)
   - `sensor.ura_house_state` — shows "away" (default initial state)
   - `sensor.ura_coordinator_summary` — shows coordinator count and status

### 3. Device hierarchy is correct

1. In **Settings > Devices & Services > Universal Room Automation**, check:
   - "URA: Zone Manager" parent device exists
   - Zone devices show "via URA: Zone Manager"
   - "URA: Coordinator Manager" parent device exists (when enabled)

### 4. Database tables created

1. Check the URA SQLite database for new tables:
   - `decision_log` — logs coordinator decisions
   - `compliance_log` — logs compliance checks
   - `house_state_log` — logs house state transitions

### 5. Tests pass

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
# Expect 375 tests passing (324 existing + 51 new)
```

---

## Graceful Degradation

| Scenario | Behavior |
|---|---|
| Domain coordinators disabled (default) | No manager created, no sensors added, no performance impact |
| No coordinators registered | Manager runs but processes nothing. Status sensor shows "idle" |
| Intent queue overflow | Logged as warning, oldest intents dropped |
| Database logging fails | Caught as non-fatal warning, coordinator continues operating |
| Python 3.9 environment | StrEnum backport activates automatically, all dataclasses compatible |

---

## Version Mapping

| External Version | Cycle | Internal Plan Reference | Feature |
|-----------------|-------|------------------------|---------|
| 3.3.5.8 | Cycle 1 | — | Bug fixes + occupancy resiliency |
| 3.3.5.9 | Cycle 2 | — | Safe service calls + HVAC zone presets |
| 3.4.0 | Cycle 3 | PLANNING_v3.5.0_CYCLE_3.md | Camera census foundation |
| 3.4.1 – 3.4.6 | Cycle 3 patches | — | Camera config at integration level + stability |
| 3.5.0 | Cycle 4 Slim | PLANNING_v3.5.1_CYCLE_4_SLIM.md | Camera occupancy extension, zone aggregation, perimeter alerting |
| 3.5.1 | Cycle 5 | PLANNING_v3.4.0_CYCLE_5.md | Consistent sensor naming |
| 3.5.2 | Cycle 6 | PLANNING_v3.5.2_CYCLE_6.md | Transit validation + warehoused sensors |
| 3.5.3 | Cycle -1 | — | Zone device duplication fix |
| **3.6.0-c0** | **C0** | **PLANNING_v3.6.0_REVISED.md** | **Domain coordinator base infrastructure (this release)** |
