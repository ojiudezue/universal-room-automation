# COORDINATOR DIAGNOSTICS FRAMEWORK v2

**Version:** 2.0
**Status:** Design Complete
**Last Updated:** 2026-02-28
**Applies To:** All URA Domain Coordinators
**Replaces:** COORDINATOR_DIAGNOSTICS_FRAMEWORK.md (v1.0, 2026-01-24)

---

## CHANGES FROM v1

This section summarizes the eight key changes from v1 to v2. Each change is referenced throughout the document where it applies.

### 1. Anomaly Definition Constrained

v1 had no formal anomaly detection. v2 defines anomaly precisely: **given historical data, is there a statistically significant deviation from normal system behavior?** Not sensor disagreements, not rule violations -- statistical deviations from learned baselines. This makes Bayesian inference the core of anomaly detection, not hardcoded thresholds.

### 2. Generalized From Energy-Only to All Coordinators

v1's `OutcomeMeasurement` was entirely energy-biased (all fields were `import_kwh`, `export_kwh`, TOU periods, battery discharge). v2 uses a base `OutcomeMeasurement` class with coordinator-specific subclasses. Each coordinator defines its own outcome metrics.

### 3. Database Pattern Fixed

v1 used raw `sqlite3.connect()` synchronously (`self.db = sqlite3.connect(db_path)`). This blocks the event loop in Home Assistant. v2 uses the existing URA `database.py` pattern with `aiosqlite` for all DB operations, consistent with the rest of the codebase.

### 4. Anomaly Detection Added as First-Class Component

New `AnomalyDetector` base class, `anomaly_log` table, `AnomalyRecord` dataclass, and per-coordinator anomaly sensor. Anomalies require a minimum sample size before activation to prevent false positives during initial data collection.

### 5. Scope Field Added

Decisions, anomalies, and compliance records now carry a `scope` field: `"house"`, `"zone:{name}"`, or `"room:{name}"`. This enables room-level and zone-level anomaly inspection in diagnostic sensors and database queries.

### 6. Diagnostic Sensor Architecture Defined

Split approach -- Coordinator Manager owns cross-cutting sensors (`system_anomaly`, `system_compliance`), each coordinator owns domain-specific sensors (`situation`, `anomaly`, `compliance`, `effectiveness`). Consistent state vocabulary across all coordinators:
- **Severity:** `"nominal"`, `"advisory"`, `"alert"`, `"critical"`
- **Learning status:** `"insufficient_data"`, `"learning"`, `"active"`, `"paused"`

### 7. Coordinator Enable/Disable Pattern

Coordinators can be disabled without deletion. The Manager is the authority -- it reads from `CONF_{ID}_ENABLED` config options. Disabled coordinators remain registered, sensors show `"disabled"`, `evaluate()` is skipped, listeners are unsubscribed. Re-enabling calls `async_setup()` again.

### 8. Learning Schedule Generalized

v1 said "weekly" for everything. v2 specifies that learning frequency depends on the coordinator's domain:
- **Energy:** Weekly (TOU patterns are stable week-to-week)
- **Presence:** Daily (occupancy patterns shift frequently)
- **Security:** Monthly (baseline events are rare, need more data per cycle)

---

## TABLE OF CONTENTS

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Decision Logging](#3-decision-logging)
4. [Compliance Tracking](#4-compliance-tracking)
5. [Outcome Measurement](#5-outcome-measurement)
6. [Anomaly Detection](#6-anomaly-detection)
7. [Pattern Analysis](#7-pattern-analysis)
8. [Bayesian Parameter Learning](#8-bayesian-parameter-learning)
9. [Diagnostic Sensors](#9-diagnostic-sensors)
10. [Coordinator Enable/Disable](#10-coordinator-enabledisable)
11. [Database Schema](#11-database-schema)
12. [Implementation Guide](#12-implementation-guide)
13. [Coordinator-Specific Extensions](#13-coordinator-specific-extensions)
14. [Quick Reference](#14-quick-reference)

---

## 1. OVERVIEW

### The Problem

Coordinators make decisions based on predictions and rules, but reality intervenes:

| Challenge | Example |
|-----------|---------|
| **Human overrides** | Someone cranks the AC during peak TOU |
| **Prediction misses** | Solar forecast was wrong by 20% |
| **Condition drift** | House thermal characteristics change seasonally |
| **No feedback loop** | Without measurement, we cannot prove savings or improve |
| **Silent anomalies** | System drifts from normal behavior with no alert |

### The Solution: Observe, Audit, Detect, Learn, Adapt

This framework provides a **reusable pattern** for all coordinators to:

1. **Log** every decision with full context and scope
2. **Track** compliance (actual vs commanded state)
3. **Measure** outcomes using coordinator-specific metrics
4. **Detect** anomalies as statistical deviations from learned baselines
5. **Analyze** patterns (when/why do overrides and anomalies happen?)
6. **Adapt** parameters through Bayesian learning

### What Is an Anomaly?

An anomaly is defined as: **given historical data, a statistically significant deviation from normal system behavior.** This means:

- It is NOT a sensor disagreement (that is a data quality issue)
- It is NOT a rule violation (that is a compliance issue)
- It IS a deviation from the learned statistical baseline for a given metric, time window, and scope

Examples:
- Presence coordinator sees 15 room transitions in an hour when the baseline is 3 +/- 1.5
- Energy coordinator sees grid import of 8 kWh during off-peak when baseline is 2.1 +/- 0.8
- Security coordinator sees 12 door open events overnight when baseline is 0.3 +/- 0.5

### Framework Benefits

| Benefit | Description |
|---------|-------------|
| **Transparency** | Know exactly why decisions were made |
| **Override Detection** | Understand when/why humans intervene |
| **Anomaly Alerting** | Statistical detection of abnormal behavior |
| **Effectiveness Measurement** | Prove actual savings per coordinator domain |
| **Self-Optimization** | Parameters improve without manual tuning |
| **Debugging** | Trace decision chains when things go wrong |
| **Scope Awareness** | Inspect diagnostics at house, zone, or room level |

---

## 2. ARCHITECTURE

### High-Level Flow

```
+-----------------------------------------------------------------------------+
|                COORDINATOR DIAGNOSTICS & LEARNING SYSTEM (v2)               |
+-----------------------------------------------------------------------------+
|                                                                             |
|   REAL-TIME LAYER (Every Decision)                                          |
|  +---------------+     +---------------+     +------------------+           |
|  |   DECISION    |---->|  COMPLIANCE   |     |    ANOMALY       |           |
|  |    LOGGING    |     |   TRACKING    |     |   DETECTION      |           |
|  |               |     |               |     |                  |           |
|  | Full context  |     | Commanded vs  |     | Statistical      |           |
|  | + scope field |     | actual state  |     | deviation from   |           |
|  | for every     |     | after delay   |     | learned baseline |           |
|  | action taken  |     | + scope field |     | (Bayesian)       |           |
|  +---------------+     +---------------+     +------------------+           |
|                                                                             |
|   PERIODIC LAYER (Coordinator-Specific Frequency)                           |
|  +-----------------------------------------------------------------------+  |
|  |                      OUTCOME MEASUREMENT                              |  |
|  |                                                                       |  |
|  |   Base class + coordinator-specific subclasses:                       |  |
|  |   Energy:   import_kwh, export_kwh, savings vs baseline              |  |
|  |   Presence: transition_accuracy, phantom_rate, decay_effectiveness   |  |
|  |   Security: alert_accuracy, false_positive_rate, response_time       |  |
|  |   Comfort:  comfort_score_avg, violations, override_count            |  |
|  |   HVAC:     efficiency_ratio, runtime_vs_target, zone_balance        |  |
|  +-----------------------------------------------------------------------+  |
|                                                                             |
|   ANALYSIS LAYER (Domain-Specific Schedule)                                 |
|  +---------------+     +---------------+     +------------------+           |
|  |    PATTERN    |---->|   BAYESIAN    |     |    ANOMALY       |           |
|  |   ANALYSIS    |     |   LEARNING    |     |    PATTERN       |           |
|  |               |     |               |     |    ANALYSIS      |           |
|  | Override      |     | Parameter     |     |                  |           |
|  | patterns,     |     | adjustment    |     | Recurring        |           |
|  | drift detect  |     | from data     |     | anomaly clusters |           |
|  +---------------+     +---------------+     +------------------+           |
|                               |                                             |
|                               v                                             |
|  +-----------------------------------------------------------------------+  |
|  |                    COORDINATOR PARAMETERS                             |  |
|  |                                                                       |  |
|  |   coast_offset: 3.0 F -> 2.5 F (learned from override patterns)      |  |
|  |   presence_decay: 300s -> 240s (learned from phantom occupancy)       |  |
|  |   door_alert_threshold: 10m -> 8m (learned from security baselines)   |  |
|  +-----------------------------------------------------------------------+  |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### Component Responsibilities

| Component | Frequency | Purpose |
|-----------|-----------|---------|
| Decision Logging | Every action | Full audit trail with scope |
| Compliance Tracking | 2 min after action | Detect overrides with scope |
| Anomaly Detection | Every outcome measurement | Statistical deviation alerts |
| Outcome Measurement | Domain-specific (see below) | Measure effectiveness |
| Pattern Analysis | Domain-specific (see below) | Find recurring patterns |
| Bayesian Learning | Domain-specific (see below) | Adjust parameters |

### Learning Schedule by Domain

| Coordinator | Outcome Measurement | Pattern Analysis | Parameter Learning | Rationale |
|-------------|--------------------|-----------------|--------------------|-----------|
| Energy | Per TOU period | Weekly | Weekly | TOU patterns are stable week-to-week |
| Presence | Hourly | Daily | Daily | Occupancy patterns shift frequently |
| Security | Daily | Monthly | Monthly | Baseline events are rare, need more samples |
| Comfort | Hourly | Weekly | Weekly | Comfort preferences are relatively stable |
| HVAC | Per HVAC cycle | Weekly | Weekly | Thermal dynamics change seasonally |

---

## 3. DECISION LOGGING

### Purpose

Record **every coordinator decision** with full context for later analysis. v2 adds the `scope` field to enable room-level and zone-level inspection.

### Data Structure

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

@dataclass
class DecisionLog:
    """Record of a coordinator decision."""

    # Identity
    timestamp: datetime
    coordinator_id: str           # "energy", "presence", "security", "comfort", "hvac"
    decision_type: str            # "tou_transition", "occupancy_update", etc.

    # v2: Scope
    scope: str                    # "house", "zone:upstairs", "room:master_bedroom"

    # Classification
    situation_classified: str     # "EXPENSIVE", "OCCUPIED", "PERIMETER_BREACH", etc.
    urgency: int                  # 0-100
    confidence: float             # 0.0-1.0

    # Inputs (everything that informed the decision)
    context: dict[str, Any]       # Full context snapshot

    # Action taken
    action: dict[str, Any]        # Full action details

    # Predictions (for later validation) -- coordinator-specific
    expected_savings_kwh: Optional[float] = None
    expected_cost_savings: Optional[float] = None
    expected_comfort_impact: Optional[int] = None  # 0-10 scale

    # Downstream effects
    constraints_published: List[str] = field(default_factory=list)
    devices_commanded: List[str] = field(default_factory=list)
```

### Implementation

All DB operations go through the existing `UniversalRoomDatabase` class via `aiosqlite`. No raw `sqlite3.connect()`.

```python
import json
import logging
from datetime import datetime
from typing import Any, Optional

import aiosqlite

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class DecisionLogger:
    """Log decisions through the existing URA database."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @property
    def _database(self):
        """Get the shared URA database instance."""
        return self.hass.data.get(DOMAIN, {}).get("database")

    async def log_decision(self, decision: "DecisionLog") -> Optional[int]:
        """Log a decision and return its ID."""
        database = self._database
        if database is None:
            return None

        try:
            async with aiosqlite.connect(database.db_file) as db:
                cursor = await db.execute("""
                    INSERT INTO decision_log
                    (timestamp, coordinator_id, decision_type, scope,
                     situation_classified, urgency, confidence,
                     context_json, action_json,
                     expected_savings_kwh, expected_cost_savings,
                     expected_comfort_impact,
                     constraints_published, devices_commanded)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    decision.timestamp.isoformat(),
                    decision.coordinator_id,
                    decision.decision_type,
                    decision.scope,
                    decision.situation_classified,
                    decision.urgency,
                    decision.confidence,
                    json.dumps(decision.context),
                    json.dumps(decision.action),
                    decision.expected_savings_kwh,
                    decision.expected_cost_savings,
                    decision.expected_comfort_impact,
                    json.dumps(decision.constraints_published),
                    json.dumps(decision.devices_commanded),
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Error logging decision: %s", e)
            return None

    async def get_decisions(
        self,
        coordinator_id: Optional[str] = None,
        scope: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> list:
        """Retrieve decisions with optional filters."""
        database = self._database
        if database is None:
            return []

        try:
            async with aiosqlite.connect(database.db_file) as db:
                db.row_factory = aiosqlite.Row
                query = "SELECT * FROM decision_log WHERE 1=1"
                params: list = []

                if coordinator_id:
                    query += " AND coordinator_id = ?"
                    params.append(coordinator_id)
                if scope:
                    query += " AND scope = ?"
                    params.append(scope)
                if start_time:
                    query += " AND timestamp >= ?"
                    params.append(start_time.isoformat())
                if end_time:
                    query += " AND timestamp <= ?"
                    params.append(end_time.isoformat())

                query += f" ORDER BY timestamp DESC LIMIT {limit}"

                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error retrieving decisions: %s", e)
            return []
```

### Usage in Coordinators

```python
class PresenceCoordinator(BaseCoordinator):
    """Example: decision logging in the Presence coordinator."""

    async def evaluate(
        self,
        intents: list,
        context: dict,
    ) -> list:
        """Evaluate intents with decision logging."""
        decision_logger = DecisionLogger(self.hass)

        # Gather situation
        room_id = intents[0].data.get("room_id", "unknown")
        transition_count = len([i for i in intents if i.source == "state_change"])

        # Log the decision
        await decision_logger.log_decision(DecisionLog(
            timestamp=datetime.utcnow(),
            coordinator_id=self.coordinator_id,
            decision_type="occupancy_evaluation",
            scope=f"room:{room_id}",
            situation_classified="OCCUPIED" if transition_count > 0 else "VACANT",
            urgency=30,
            confidence=0.85,
            context={
                "house_state": str(context.get("house_state")),
                "transition_count": transition_count,
                "room_id": room_id,
            },
            action={"type": "update_occupancy"},
            devices_commanded=[],
        ))

        # ... return actions
        return []
```

---

## 4. COMPLIANCE TRACKING

### Purpose

Track whether devices **actually followed** commands, detecting human overrides. v2 adds the `scope` field and uses `aiosqlite` instead of raw `sqlite3`.

### Data Structure

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class ComplianceRecord:
    """Track actual vs commanded state."""

    timestamp: datetime
    decision_id: int              # Links to decision_log

    # v2: Scope
    scope: str                    # "house", "zone:upstairs", "room:master_bedroom"

    device_type: str              # "light", "fan", "climate", "switch", "cover"
    device_id: str                # Entity ID

    # What was commanded
    commanded_state: dict[str, Any]

    # What actually happened
    actual_state: dict[str, Any]

    # Analysis
    compliant: bool
    deviation_details: Optional[dict] = None

    # Override detection
    override_detected: bool = False
    override_source: Optional[str] = None   # "manual", "app", "schedule", "automation"
    override_duration_minutes: Optional[int] = None
```

### Implementation

```python
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional

import aiosqlite

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ComplianceTracker:
    """Track compliance with coordinator commands using aiosqlite."""

    COMPLIANCE_CHECK_DELAY = 120  # Seconds to wait before checking

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @property
    def _database(self):
        """Get the shared URA database instance."""
        return self.hass.data.get(DOMAIN, {}).get("database")

    async def schedule_check(
        self,
        decision_id: int,
        scope: str,
        device_type: str,
        device_id: str,
        commanded_state: dict,
    ) -> None:
        """Schedule a compliance check after command execution."""

        async def _delayed_check(_now: Any = None) -> None:
            await self._check_compliance(
                decision_id, scope, device_type, device_id, commanded_state
            )

        async_call_later(
            self.hass,
            self.COMPLIANCE_CHECK_DELAY,
            _delayed_check,
        )

    async def _check_compliance(
        self,
        decision_id: int,
        scope: str,
        device_type: str,
        device_id: str,
        commanded_state: dict,
    ) -> Optional[ComplianceRecord]:
        """Check if device complied with command."""
        state = self.hass.states.get(device_id)
        actual_state = self._extract_state(state, device_type)

        compliant, deviation = self._compare_states(
            commanded_state, actual_state, device_type
        )

        override_source = None
        if not compliant:
            override_source = await self._detect_override_source(
                device_id, device_type
            )

        record = ComplianceRecord(
            timestamp=datetime.utcnow(),
            decision_id=decision_id,
            scope=scope,
            device_type=device_type,
            device_id=device_id,
            commanded_state=commanded_state,
            actual_state=actual_state,
            compliant=compliant,
            deviation_details=deviation,
            override_detected=not compliant,
            override_source=override_source,
        )

        await self._store_compliance(record)
        return record

    def _compare_states(
        self,
        commanded: dict,
        actual: dict,
        device_type: str,
    ) -> tuple:
        """Compare commanded vs actual state.

        Returns (compliant: bool, deviation: Optional[dict]).
        """
        if device_type == "climate":
            cmd_setpoint = commanded.get("target_temp_high")
            act_setpoint = actual.get("target_temp_high")
            if cmd_setpoint and act_setpoint:
                if abs(cmd_setpoint - act_setpoint) > 1.0:
                    return False, {
                        "field": "target_temp_high",
                        "commanded": cmd_setpoint,
                        "actual": act_setpoint,
                        "delta": act_setpoint - cmd_setpoint,
                    }

            cmd_preset = commanded.get("preset_mode")
            act_preset = actual.get("preset_mode")
            if cmd_preset and act_preset and cmd_preset != act_preset:
                return False, {
                    "field": "preset_mode",
                    "commanded": cmd_preset,
                    "actual": act_preset,
                }

        elif device_type in ("light", "fan", "switch"):
            cmd_on = commanded.get("state") == "on"
            act_on = actual.get("state") == "on"
            if cmd_on != act_on:
                return False, {
                    "field": "state",
                    "commanded": "on" if cmd_on else "off",
                    "actual": "on" if act_on else "off",
                }

        elif device_type == "cover":
            cmd_pos = commanded.get("position")
            act_pos = actual.get("position")
            if cmd_pos is not None and act_pos is not None:
                if abs(cmd_pos - act_pos) > 5:
                    return False, {
                        "field": "position",
                        "commanded": cmd_pos,
                        "actual": act_pos,
                        "delta": act_pos - cmd_pos,
                    }

        return True, None

    def _extract_state(self, state: Any, device_type: str) -> dict:
        """Extract relevant state based on device type."""
        if not state:
            return {}

        if device_type == "climate":
            return {
                "hvac_mode": state.state,
                "preset_mode": state.attributes.get("preset_mode"),
                "target_temp_high": state.attributes.get("target_temp_high"),
                "target_temp_low": state.attributes.get("target_temp_low"),
            }
        elif device_type == "cover":
            return {
                "state": state.state,
                "position": state.attributes.get("current_position"),
            }
        return {"state": state.state}

    async def _detect_override_source(
        self,
        device_id: str,
        device_type: str,
    ) -> str:
        """Attempt to detect what caused the override."""
        if device_type == "climate":
            state = self.hass.states.get(device_id)
            if state and state.attributes.get("preset_mode") == "manual":
                return "thermostat_manual"
        return "unknown"

    async def _store_compliance(self, record: ComplianceRecord) -> None:
        """Store compliance record via the URA database."""
        database = self._database
        if database is None:
            return

        try:
            await database.log_compliance_check(
                decision_id=record.decision_id,
                device_type=record.device_type,
                device_id=record.device_id,
                commanded_state=json.dumps(record.commanded_state),
                actual_state=json.dumps(record.actual_state),
                compliant=record.compliant,
                deviation_details=(
                    json.dumps(record.deviation_details)
                    if record.deviation_details else None
                ),
                override_detected=record.override_detected,
                override_source=record.override_source,
                override_duration_minutes=record.override_duration_minutes,
            )
        except Exception as e:
            _LOGGER.error("Error storing compliance record: %s", e)

    async def get_compliance_rate(
        self,
        coordinator_id: Optional[str] = None,
        scope: Optional[str] = None,
        days: int = 7,
    ) -> float:
        """Get compliance rate for recent period."""
        database = self._database
        if database is None:
            return 1.0

        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        try:
            async with aiosqlite.connect(database.db_file) as db:
                query = """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN c.compliant THEN 1 ELSE 0 END) as compliant_count
                    FROM compliance_log c
                    JOIN decision_log d ON c.decision_id = d.id
                    WHERE c.timestamp >= ?
                """
                params: list = [cutoff]

                if coordinator_id:
                    query += " AND d.coordinator_id = ?"
                    params.append(coordinator_id)
                if scope:
                    query += " AND d.scope = ?"
                    params.append(scope)

                cursor = await db.execute(query, params)
                row = await cursor.fetchone()

                if row and row[0] > 0:
                    return row[1] / row[0]
                return 1.0
        except Exception as e:
            _LOGGER.error("Error getting compliance rate: %s", e)
            return 1.0
```

---

## 5. OUTCOME MEASUREMENT

### Purpose

Measure **actual results** to validate coordinator effectiveness. v2 replaces the energy-only `OutcomeMeasurement` with a base class and coordinator-specific subclasses.

### Base Class

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class OutcomeMeasurement:
    """Base class for coordinator outcome measurements.

    Each coordinator subclasses this with domain-specific metrics.
    The base class carries identity, scope, and shared fields.
    """

    # Identity
    timestamp: datetime
    coordinator_id: str
    period_start: datetime
    period_end: datetime

    # v2: Scope
    scope: str                    # "house", "zone:upstairs", "room:kitchen"

    # Shared outcome fields
    decisions_in_period: int = 0
    compliance_rate: float = 1.0
    override_count: int = 0

    # Subclass stores domain-specific metrics here
    metrics: Dict[str, Any] = field(default_factory=dict)
```

### Energy Outcome Subclass

```python
@dataclass
class EnergyOutcome(OutcomeMeasurement):
    """Outcome measurement for the Energy coordinator."""

    coordinator_id: str = "energy"

    # Energy-specific metrics
    import_kwh: float = 0.0
    export_kwh: float = 0.0
    solar_production_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0

    # Cost metrics
    actual_cost: float = 0.0
    baseline_cost: float = 0.0
    savings: float = 0.0

    # Prediction accuracy
    solar_predicted_kwh: float = 0.0
    solar_error_pct: float = 0.0
    load_predicted_kwh: float = 0.0
    load_error_pct: float = 0.0

    # TOU-specific
    tou_period: str = ""          # "off_peak", "mid_peak", "peak"
```

### Presence Outcome Subclass

```python
@dataclass
class PresenceOutcome(OutcomeMeasurement):
    """Outcome measurement for the Presence coordinator."""

    coordinator_id: str = "presence"

    # Presence-specific metrics
    room_transitions: int = 0
    phantom_occupancy_events: int = 0       # Room marked occupied with nobody there
    missed_occupancy_events: int = 0        # Room was occupied but not detected
    transition_accuracy: float = 1.0        # Correct transitions / total transitions
    avg_detection_latency_seconds: float = 0.0
    decay_timeout_effectiveness: float = 1.0  # Correct timeouts / total timeouts
    persons_tracked: int = 0
    rooms_monitored: int = 0
```

### Security Outcome Subclass

```python
@dataclass
class SecurityOutcome(OutcomeMeasurement):
    """Outcome measurement for the Security coordinator."""

    coordinator_id: str = "security"

    # Security-specific metrics
    alerts_generated: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    alert_accuracy: float = 1.0
    avg_response_time_seconds: float = 0.0
    perimeter_events: int = 0
    door_open_violations: int = 0
    window_open_violations: int = 0
```

### Outcome Measurer

```python
import json
import logging
from datetime import datetime
from typing import Optional

import aiosqlite

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OutcomeMeasurer:
    """Measure and record outcomes for any coordinator type."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @property
    def _database(self):
        """Get the shared URA database instance."""
        return self.hass.data.get(DOMAIN, {}).get("database")

    async def store_outcome(self, outcome: OutcomeMeasurement) -> Optional[int]:
        """Store an outcome measurement."""
        database = self._database
        if database is None:
            return None

        try:
            async with aiosqlite.connect(database.db_file) as db:
                cursor = await db.execute("""
                    INSERT INTO outcome_log
                    (timestamp, coordinator_id, scope,
                     period_start, period_end,
                     decisions_in_period, compliance_rate, override_count,
                     metrics_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    outcome.timestamp.isoformat(),
                    outcome.coordinator_id,
                    outcome.scope,
                    outcome.period_start.isoformat(),
                    outcome.period_end.isoformat(),
                    outcome.decisions_in_period,
                    outcome.compliance_rate,
                    outcome.override_count,
                    json.dumps(self._extract_metrics(outcome)),
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Error storing outcome: %s", e)
            return None

    def _extract_metrics(self, outcome: OutcomeMeasurement) -> dict:
        """Extract coordinator-specific metrics from the outcome.

        Serializes all fields that are not in the base class into metrics_json.
        """
        base_fields = {
            "timestamp", "coordinator_id", "period_start", "period_end",
            "scope", "decisions_in_period", "compliance_rate",
            "override_count", "metrics",
        }
        result = dict(outcome.metrics)
        for key, value in outcome.__dict__.items():
            if key not in base_fields:
                result[key] = value
        return result

    async def get_outcomes(
        self,
        coordinator_id: str,
        scope: Optional[str] = None,
        days: int = 30,
        limit: int = 500,
    ) -> list:
        """Retrieve outcome records."""
        database = self._database
        if database is None:
            return []

        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        try:
            async with aiosqlite.connect(database.db_file) as db:
                db.row_factory = aiosqlite.Row
                query = """
                    SELECT * FROM outcome_log
                    WHERE coordinator_id = ? AND timestamp >= ?
                """
                params: list = [coordinator_id, cutoff]

                if scope:
                    query += " AND scope = ?"
                    params.append(scope)

                query += f" ORDER BY timestamp DESC LIMIT {limit}"

                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error retrieving outcomes: %s", e)
            return []
```

---

## 6. ANOMALY DETECTION

### Purpose

Detect **statistically significant deviations** from normal system behavior using Bayesian inference. This is a new first-class component in v2.

### Core Principle

An anomaly is a data point (or set of data points) that is unlikely given the learned distribution of normal behavior. We use a Gaussian model for each tracked metric:

```
P(anomaly | data) = P(data | anomaly) * P(anomaly) / P(data)
```

In practice, for each metric we maintain a running mean and standard deviation. A z-score above a threshold triggers an anomaly. The threshold adapts based on sample size -- more data means tighter bounds.

### Minimum Sample Sizes

Anomaly detection requires a minimum number of observations before activating. This prevents false positives during initial data collection.

| Coordinator | Minimum Samples | Rationale |
|-------------|----------------|-----------|
| Energy | 48 (2 days of hourly) | Need at least two full daily cycles |
| Presence | 24 (1 day of hourly) | Occupancy patterns repeat daily |
| Security | 168 (1 week of hourly) | Security events are sparse |
| Comfort | 48 (2 days of hourly) | Comfort preferences stabilize quickly |
| HVAC | 48 (2 days of hourly) | Need heating and cooling cycle data |

### Data Structures

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class AnomalySeverity(StrEnum):
    """Severity levels for anomalies."""
    NOMINAL = "nominal"
    ADVISORY = "advisory"        # z-score 2.0-3.0: unusual but not alarming
    ALERT = "alert"              # z-score 3.0-4.0: significant deviation
    CRITICAL = "critical"        # z-score > 4.0: extreme deviation


@dataclass
class AnomalyRecord:
    """Record of a detected anomaly."""

    timestamp: datetime
    coordinator_id: str
    scope: str                    # "house", "zone:upstairs", "room:kitchen"

    # What was anomalous
    metric_name: str              # "room_transitions", "grid_import_kwh", etc.
    observed_value: float
    expected_mean: float
    expected_std: float
    z_score: float

    # Severity classification
    severity: AnomalySeverity
    sample_size: int              # How many observations built the baseline

    # Context
    house_state: str              # HouseState at time of anomaly
    context: Dict[str, Any] = field(default_factory=dict)

    # Resolution
    resolved: bool = False
    resolution_notes: Optional[str] = None


@dataclass
class MetricBaseline:
    """Running statistics for a single metric."""

    metric_name: str
    coordinator_id: str
    scope: str

    # Gaussian parameters
    mean: float = 0.0
    variance: float = 1.0
    sample_count: int = 0

    # Metadata
    last_updated: Optional[str] = None

    @property
    def std(self) -> float:
        """Standard deviation."""
        import math
        return math.sqrt(self.variance) if self.variance > 0 else 0.001

    @property
    def is_active(self) -> bool:
        """Whether enough samples have been collected to detect anomalies."""
        # Subclasses / callers check against their minimum sample threshold
        return self.sample_count >= 24  # Default minimum

    def update(self, value: float) -> None:
        """Update running statistics with Welford's online algorithm.

        This is numerically stable for computing running mean and variance.
        """
        self.sample_count += 1
        delta = value - self.mean
        self.mean += delta / self.sample_count
        delta2 = value - self.mean
        self.variance = (
            (self.variance * (self.sample_count - 1) + delta * delta2)
            / self.sample_count
        ) if self.sample_count > 1 else 0.0
        self.last_updated = datetime.utcnow().isoformat()

    def z_score(self, value: float) -> float:
        """Compute z-score for a given value."""
        if self.std < 0.001:
            return 0.0
        return abs(value - self.mean) / self.std
```

### AnomalyDetector Base Class

```python
import json
import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class AnomalyDetector:
    """Base anomaly detector using Bayesian/statistical methods.

    Each coordinator instantiates this with its own metric definitions
    and minimum sample sizes.
    """

    # Subclasses override these
    MINIMUM_SAMPLES: int = 24
    Z_SCORE_ADVISORY: float = 2.0
    Z_SCORE_ALERT: float = 3.0
    Z_SCORE_CRITICAL: float = 4.0

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator_id: str,
        metric_names: List[str],
        minimum_samples: Optional[int] = None,
    ) -> None:
        self.hass = hass
        self.coordinator_id = coordinator_id
        self.metric_names = metric_names
        self.minimum_samples = minimum_samples or self.MINIMUM_SAMPLES

        # Baselines keyed by (metric_name, scope)
        self._baselines: Dict[tuple, MetricBaseline] = {}

    @property
    def _database(self):
        """Get the shared URA database instance."""
        return self.hass.data.get(DOMAIN, {}).get("database")

    def _get_baseline(self, metric_name: str, scope: str) -> MetricBaseline:
        """Get or create a baseline for a metric+scope pair."""
        key = (metric_name, scope)
        if key not in self._baselines:
            self._baselines[key] = MetricBaseline(
                metric_name=metric_name,
                coordinator_id=self.coordinator_id,
                scope=scope,
            )
        return self._baselines[key]

    def record_observation(
        self,
        metric_name: str,
        scope: str,
        value: float,
    ) -> Optional[AnomalyRecord]:
        """Record an observation and check for anomaly.

        Returns an AnomalyRecord if an anomaly is detected, None otherwise.
        """
        baseline = self._get_baseline(metric_name, scope)

        # Check for anomaly BEFORE updating baseline (so the observation
        # is compared against the prior distribution)
        anomaly = None
        if baseline.sample_count >= self.minimum_samples:
            z = baseline.z_score(value)
            severity = self._classify_severity(z)
            if severity != AnomalySeverity.NOMINAL:
                anomaly = AnomalyRecord(
                    timestamp=datetime.utcnow(),
                    coordinator_id=self.coordinator_id,
                    scope=scope,
                    metric_name=metric_name,
                    observed_value=value,
                    expected_mean=baseline.mean,
                    expected_std=baseline.std,
                    z_score=z,
                    severity=severity,
                    sample_size=baseline.sample_count,
                    house_state="",  # Caller fills this in
                )

        # Update the baseline with the new observation
        baseline.update(value)

        return anomaly

    def _classify_severity(self, z_score: float) -> AnomalySeverity:
        """Classify anomaly severity based on z-score."""
        if z_score >= self.Z_SCORE_CRITICAL:
            return AnomalySeverity.CRITICAL
        elif z_score >= self.Z_SCORE_ALERT:
            return AnomalySeverity.ALERT
        elif z_score >= self.Z_SCORE_ADVISORY:
            return AnomalySeverity.ADVISORY
        return AnomalySeverity.NOMINAL

    def get_learning_status(self, scope: str = "house") -> str:
        """Return the learning status for a given scope.

        Returns one of: "insufficient_data", "learning", "active", "paused".
        """
        active_metrics = 0
        learning_metrics = 0
        for metric_name in self.metric_names:
            baseline = self._get_baseline(metric_name, scope)
            if baseline.sample_count >= self.minimum_samples:
                active_metrics += 1
            elif baseline.sample_count > 0:
                learning_metrics += 1

        if active_metrics == len(self.metric_names):
            return "active"
        elif active_metrics > 0 or learning_metrics > 0:
            return "learning"
        return "insufficient_data"

    def get_status_summary(self, scope: str = "house") -> dict:
        """Return a summary of anomaly detection status for diagnostics."""
        summary: Dict[str, Any] = {
            "coordinator_id": self.coordinator_id,
            "scope": scope,
            "learning_status": self.get_learning_status(scope),
            "minimum_samples": self.minimum_samples,
            "metrics": {},
        }
        for metric_name in self.metric_names:
            baseline = self._get_baseline(metric_name, scope)
            summary["metrics"][metric_name] = {
                "mean": round(baseline.mean, 4),
                "std": round(baseline.std, 4),
                "sample_count": baseline.sample_count,
                "active": baseline.sample_count >= self.minimum_samples,
            }
        return summary

    async def store_anomaly(self, anomaly: AnomalyRecord) -> Optional[int]:
        """Store an anomaly record in the database."""
        database = self._database
        if database is None:
            return None

        try:
            async with aiosqlite.connect(database.db_file) as db:
                cursor = await db.execute("""
                    INSERT INTO anomaly_log
                    (timestamp, coordinator_id, scope,
                     metric_name, observed_value,
                     expected_mean, expected_std, z_score,
                     severity, sample_size, house_state,
                     context_json, resolved, resolution_notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    anomaly.timestamp.isoformat(),
                    anomaly.coordinator_id,
                    anomaly.scope,
                    anomaly.metric_name,
                    anomaly.observed_value,
                    anomaly.expected_mean,
                    anomaly.expected_std,
                    anomaly.z_score,
                    anomaly.severity.value,
                    anomaly.sample_size,
                    anomaly.house_state,
                    json.dumps(anomaly.context),
                    anomaly.resolved,
                    anomaly.resolution_notes,
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Error storing anomaly: %s", e)
            return None

    async def load_baselines(self) -> None:
        """Load baseline statistics from the database."""
        database = self._database
        if database is None:
            return

        try:
            async with aiosqlite.connect(database.db_file) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT metric_name, scope, mean, variance,
                           sample_count, last_updated
                    FROM metric_baselines
                    WHERE coordinator_id = ?
                """, (self.coordinator_id,))
                rows = await cursor.fetchall()

                for row in rows:
                    key = (row["metric_name"], row["scope"])
                    self._baselines[key] = MetricBaseline(
                        metric_name=row["metric_name"],
                        coordinator_id=self.coordinator_id,
                        scope=row["scope"],
                        mean=row["mean"],
                        variance=row["variance"],
                        sample_count=row["sample_count"],
                        last_updated=row["last_updated"],
                    )
        except Exception as e:
            _LOGGER.debug("Error loading baselines (may not exist yet): %s", e)

    async def save_baselines(self) -> None:
        """Persist baseline statistics to the database."""
        database = self._database
        if database is None:
            return

        try:
            async with aiosqlite.connect(database.db_file) as db:
                for key, baseline in self._baselines.items():
                    await db.execute("""
                        INSERT OR REPLACE INTO metric_baselines
                        (coordinator_id, metric_name, scope,
                         mean, variance, sample_count, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        baseline.coordinator_id,
                        baseline.metric_name,
                        baseline.scope,
                        baseline.mean,
                        baseline.variance,
                        baseline.sample_count,
                        baseline.last_updated,
                    ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving baselines: %s", e)
```

### Coordinator-Specific Anomaly Detectors

```python
class PresenceAnomalyDetector(AnomalyDetector):
    """Anomaly detection for the Presence coordinator."""

    MINIMUM_SAMPLES = 24  # 1 day of hourly observations

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass=hass,
            coordinator_id="presence",
            metric_names=[
                "room_transitions_per_hour",
                "phantom_occupancy_rate",
                "avg_occupancy_duration_minutes",
                "simultaneous_rooms_occupied",
            ],
            minimum_samples=self.MINIMUM_SAMPLES,
        )


class EnergyAnomalyDetector(AnomalyDetector):
    """Anomaly detection for the Energy coordinator."""

    MINIMUM_SAMPLES = 48  # 2 days of hourly observations

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass=hass,
            coordinator_id="energy",
            metric_names=[
                "grid_import_kwh_per_hour",
                "solar_production_kwh_per_hour",
                "baseline_cost_deviation_pct",
                "battery_efficiency_ratio",
            ],
            minimum_samples=self.MINIMUM_SAMPLES,
        )


class SecurityAnomalyDetector(AnomalyDetector):
    """Anomaly detection for the Security coordinator."""

    MINIMUM_SAMPLES = 168  # 1 week of hourly observations

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass=hass,
            coordinator_id="security",
            metric_names=[
                "door_events_per_hour",
                "window_events_per_hour",
                "perimeter_alerts_per_day",
                "after_hours_activity_count",
            ],
            minimum_samples=self.MINIMUM_SAMPLES,
        )
```

### Usage in a Coordinator

```python
class PresenceCoordinator(BaseCoordinator):
    """Presence coordinator with anomaly detection."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass, "presence", "Presence", priority=60)
        self._anomaly_detector = PresenceAnomalyDetector(hass)

    async def async_setup(self) -> None:
        """Set up -- load baselines from DB."""
        await self._anomaly_detector.load_baselines()

    async def evaluate(self, intents: list, context: dict) -> list:
        """Evaluate with anomaly detection."""
        # Count transitions in this batch
        room_id = intents[0].data.get("room_id", "unknown")
        transitions = len([i for i in intents if i.source == "state_change"])

        # Record observation and check for anomaly
        anomaly = self._anomaly_detector.record_observation(
            metric_name="room_transitions_per_hour",
            scope=f"room:{room_id}",
            value=float(transitions),
        )

        if anomaly is not None:
            anomaly.house_state = str(context.get("house_state", ""))
            anomaly.context = {"room_id": room_id}
            await self._anomaly_detector.store_anomaly(anomaly)
            _LOGGER.warning(
                "Anomaly detected: %s in %s (z=%.1f, observed=%.1f, expected=%.1f +/- %.1f)",
                anomaly.metric_name,
                anomaly.scope,
                anomaly.z_score,
                anomaly.observed_value,
                anomaly.expected_mean,
                anomaly.expected_std,
            )

        # ... normal evaluation logic
        return []

    async def async_teardown(self) -> None:
        """Tear down -- save baselines to DB."""
        await self._anomaly_detector.save_baselines()
        self._cancel_listeners()
```

---

## 7. PATTERN ANALYSIS

### Purpose

Analyze **recurring patterns** in overrides, outcomes, and anomalies for insights.

### Override Pattern Detection

```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class OverridePattern:
    """A detected pattern in user overrides."""

    description: str              # Human-readable
    condition: str                # "outdoor_temp > 95", "hour between 17-20"
    frequency: float              # 0.0-1.0
    confidence: float             # Statistical confidence
    sample_size: int
    scope: str                    # "house", "zone:upstairs", "room:kitchen"
    recommendation: Optional[str] = None
```

### Pattern Analyzer

```python
import json
import logging
import math
from datetime import datetime, timedelta
from typing import List, Optional

import aiosqlite

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class PatternAnalyzer:
    """Analyze override, outcome, and anomaly patterns."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @property
    def _database(self):
        return self.hass.data.get(DOMAIN, {}).get("database")

    async def analyze_override_patterns(
        self,
        coordinator_id: Optional[str] = None,
        scope: Optional[str] = None,
        days: int = 30,
    ) -> List[OverridePattern]:
        """Find patterns in user overrides."""
        overrides = await self._get_overrides_with_context(
            coordinator_id, scope, days
        )

        if len(overrides) < 10:
            return []

        patterns: List[OverridePattern] = []
        effective_scope = scope or "house"

        # Analyze by time of day
        patterns.extend(
            self._analyze_by_time(overrides, effective_scope)
        )

        # Analyze by day of week
        patterns.extend(
            self._analyze_by_day_of_week(overrides, effective_scope)
        )

        # Analyze by house state
        patterns.extend(
            self._analyze_by_house_state(overrides, effective_scope)
        )

        return sorted(patterns, key=lambda p: -p.frequency)

    async def analyze_anomaly_patterns(
        self,
        coordinator_id: Optional[str] = None,
        scope: Optional[str] = None,
        days: int = 30,
    ) -> List[dict]:
        """Analyze recurring anomaly clusters.

        Groups anomalies by metric, time-of-day, and scope to find
        systematic issues.
        """
        database = self._database
        if database is None:
            return []

        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        try:
            async with aiosqlite.connect(database.db_file) as db:
                db.row_factory = aiosqlite.Row
                query = """
                    SELECT metric_name, scope, severity,
                           COUNT(*) as count,
                           AVG(z_score) as avg_z_score,
                           AVG(observed_value) as avg_observed,
                           AVG(expected_mean) as avg_expected
                    FROM anomaly_log
                    WHERE timestamp >= ?
                """
                params: list = [cutoff]

                if coordinator_id:
                    query += " AND coordinator_id = ?"
                    params.append(coordinator_id)
                if scope:
                    query += " AND scope = ?"
                    params.append(scope)

                query += " GROUP BY metric_name, scope, severity"
                query += " HAVING count >= 3"
                query += " ORDER BY count DESC"

                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error analyzing anomaly patterns: %s", e)
            return []

    def _analyze_by_time(
        self, overrides: list, scope: str
    ) -> List[OverridePattern]:
        """Find time-of-day override patterns."""
        patterns: List[OverridePattern] = []

        evening_overrides = [
            o for o in overrides if 17 <= o.get("hour", 0) <= 20
        ]
        if evening_overrides:
            freq = len(evening_overrides) / len(overrides)
            if freq > 0.4:
                patterns.append(OverridePattern(
                    description=(
                        f"User overrides {freq:.0%} of time "
                        f"during evening (5-8pm)"
                    ),
                    condition="hour between 17-20",
                    frequency=freq,
                    confidence=self._wilson_confidence(
                        len(evening_overrides), len(overrides)
                    ),
                    sample_size=len(evening_overrides),
                    scope=scope,
                    recommendation=(
                        "Evening comfort may be higher priority than savings"
                    ),
                ))

        morning_overrides = [
            o for o in overrides if 6 <= o.get("hour", 0) <= 8
        ]
        if morning_overrides:
            freq = len(morning_overrides) / len(overrides)
            if freq > 0.3:
                patterns.append(OverridePattern(
                    description=(
                        f"User overrides {freq:.0%} of time "
                        f"during morning (6-8am)"
                    ),
                    condition="hour between 6-8",
                    frequency=freq,
                    confidence=self._wilson_confidence(
                        len(morning_overrides), len(overrides)
                    ),
                    sample_size=len(morning_overrides),
                    scope=scope,
                    recommendation=(
                        "Morning routine may need different parameters"
                    ),
                ))

        return patterns

    def _analyze_by_day_of_week(
        self, overrides: list, scope: str
    ) -> List[OverridePattern]:
        """Find day-of-week override patterns."""
        patterns: List[OverridePattern] = []

        weekend_overrides = [
            o for o in overrides if o.get("weekday", 0) >= 5
        ]
        if weekend_overrides:
            freq = len(weekend_overrides) / len(overrides)
            # Weekends are 2/7 = 0.286 of the week, so > 0.4 is overrepresented
            if freq > 0.4:
                patterns.append(OverridePattern(
                    description=(
                        f"User overrides {freq:.0%} of time on weekends "
                        f"(expected ~29%)"
                    ),
                    condition="weekday >= 5",
                    frequency=freq,
                    confidence=self._wilson_confidence(
                        len(weekend_overrides), len(overrides)
                    ),
                    sample_size=len(weekend_overrides),
                    scope=scope,
                    recommendation="Consider separate weekend parameters",
                ))

        return patterns

    def _analyze_by_house_state(
        self, overrides: list, scope: str
    ) -> List[OverridePattern]:
        """Find house-state-correlated override patterns."""
        patterns: List[OverridePattern] = []

        sleep_overrides = [
            o for o in overrides
            if o.get("house_state") in ("sleep", "home_night")
        ]
        if sleep_overrides and len(overrides) > 0:
            freq = len(sleep_overrides) / len(overrides)
            if freq > 0.3:
                patterns.append(OverridePattern(
                    description=(
                        f"User overrides {freq:.0%} of time during "
                        f"sleep/night hours"
                    ),
                    condition="house_state in (sleep, home_night)",
                    frequency=freq,
                    confidence=self._wilson_confidence(
                        len(sleep_overrides), len(overrides)
                    ),
                    sample_size=len(sleep_overrides),
                    scope=scope,
                    recommendation=(
                        "Night/sleep comfort thresholds may be too aggressive"
                    ),
                ))

        return patterns

    def _wilson_confidence(self, successes: int, total: int) -> float:
        """Calculate statistical confidence using Wilson score interval."""
        if total == 0:
            return 0.0
        z = 1.96  # 95% confidence
        p = successes / total
        denominator = 1 + z * z / total
        center = p + z * z / (2 * total)
        spread = z * math.sqrt(
            (p * (1 - p) + z * z / (4 * total)) / total
        )
        lower_bound = (center - spread) / denominator
        return max(0.0, lower_bound)

    async def _get_overrides_with_context(
        self,
        coordinator_id: Optional[str],
        scope: Optional[str],
        days: int,
    ) -> list:
        """Get override records with decision context."""
        database = self._database
        if database is None:
            return []

        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        try:
            async with aiosqlite.connect(database.db_file) as db:
                db.row_factory = aiosqlite.Row
                query = """
                    SELECT c.*, d.context_json, d.scope
                    FROM compliance_log c
                    JOIN decision_log d ON c.decision_id = d.id
                    WHERE c.override_detected = 1
                    AND c.timestamp >= ?
                """
                params: list = [cutoff]

                if coordinator_id:
                    query += " AND d.coordinator_id = ?"
                    params.append(coordinator_id)
                if scope:
                    query += " AND d.scope = ?"
                    params.append(scope)

                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()

                results = []
                for row in rows:
                    record = dict(row)
                    context = json.loads(record.get("context_json", "{}"))
                    record["outdoor_temp"] = context.get("outdoor_temp_f", 0)
                    record["house_state"] = context.get("house_state", "")
                    ts = record.get("timestamp", "")
                    if ts:
                        dt = datetime.fromisoformat(ts)
                        record["hour"] = dt.hour
                        record["weekday"] = dt.weekday()
                    results.append(record)

                return results
        except Exception as e:
            _LOGGER.error("Error getting overrides: %s", e)
            return []
```

---

## 8. BAYESIAN PARAMETER LEARNING

### Purpose

**Automatically adjust** coordinator parameters based on observed data. v2 connects the parameter learner to anomaly detection output and uses `aiosqlite` for all DB operations.

### Implementation

```python
import json
import logging
import math
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class ParameterBelief:
    """Bayesian belief about a parameter value.

    Uses a Gaussian posterior: N(mean, std^2).
    Updated via conjugate Gaussian updates.
    """

    mean: float
    std: float
    min_value: Optional[float] = None   # Hard lower bound
    max_value: Optional[float] = None   # Hard upper bound

    def sample(self) -> float:
        """Sample from the belief distribution."""
        value = random.gauss(self.mean, self.std)
        if self.min_value is not None:
            value = max(self.min_value, value)
        if self.max_value is not None:
            value = min(self.max_value, value)
        return value

    def update(
        self, observation: float, weight: float = 1.0
    ) -> "ParameterBelief":
        """Bayesian update with new observation.

        Uses conjugate Gaussian update:
        posterior_precision = prior_precision + observation_precision
        posterior_mean = weighted average of prior mean and observation
        """
        prior_precision = 1.0 / (self.std ** 2) if self.std > 0.01 else 100.0
        obs_precision = weight

        total_precision = prior_precision + obs_precision
        new_mean = (
            (self.mean * prior_precision + observation * obs_precision)
            / total_precision
        )
        new_std = math.sqrt(1.0 / total_precision)

        # Apply bounds
        if self.min_value is not None:
            new_mean = max(self.min_value, new_mean)
        if self.max_value is not None:
            new_mean = min(self.max_value, new_mean)

        # Floor on std to prevent over-certainty
        new_std = max(0.05, new_std)

        return ParameterBelief(
            mean=new_mean,
            std=new_std,
            min_value=self.min_value,
            max_value=self.max_value,
        )


class BayesianParameterLearner:
    """Learn optimal coordinator parameters from observed outcomes.

    Each coordinator creates a learner with its own parameter definitions.
    All DB operations go through aiosqlite.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator_id: str,
        default_beliefs: Dict[str, ParameterBelief],
    ) -> None:
        self.hass = hass
        self.coordinator_id = coordinator_id
        self.beliefs: Dict[str, ParameterBelief] = dict(default_beliefs)

    @property
    def _database(self):
        return self.hass.data.get(DOMAIN, {}).get("database")

    async def load_beliefs(self) -> None:
        """Load persisted beliefs from the database."""
        database = self._database
        if database is None:
            return

        try:
            async with aiosqlite.connect(database.db_file) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT parameter_name, mean, std
                    FROM parameter_beliefs
                    WHERE coordinator_id = ?
                """, (self.coordinator_id,))
                rows = await cursor.fetchall()

                for row in rows:
                    name = row["parameter_name"]
                    if name in self.beliefs:
                        old = self.beliefs[name]
                        self.beliefs[name] = ParameterBelief(
                            mean=row["mean"],
                            std=row["std"],
                            min_value=old.min_value,
                            max_value=old.max_value,
                        )
        except Exception as e:
            _LOGGER.debug("Error loading beliefs: %s", e)

    async def save_beliefs(self) -> None:
        """Persist beliefs to the database."""
        database = self._database
        if database is None:
            return

        try:
            async with aiosqlite.connect(database.db_file) as db:
                for name, belief in self.beliefs.items():
                    await db.execute("""
                        INSERT OR REPLACE INTO parameter_beliefs
                        (coordinator_id, parameter_name, mean, std, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        self.coordinator_id,
                        name,
                        belief.mean,
                        belief.std,
                        datetime.utcnow().isoformat(),
                    ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving beliefs: %s", e)

    async def update_parameter(
        self,
        name: str,
        observation: float,
        weight: float = 1.0,
        reason: str = "bayesian_update",
    ) -> Optional[float]:
        """Update a single parameter belief and log the change."""
        if name not in self.beliefs:
            _LOGGER.warning("Unknown parameter: %s", name)
            return None

        old_value = self.beliefs[name].mean
        self.beliefs[name] = self.beliefs[name].update(observation, weight)
        new_value = self.beliefs[name].mean

        await self._log_parameter_change(name, old_value, new_value, reason)
        return new_value

    def get_parameters(self) -> Dict[str, float]:
        """Get current parameter values (means) for coordinator use."""
        return {name: belief.mean for name, belief in self.beliefs.items()}

    def get_parameter_with_exploration(
        self, name: str, exploration_rate: float = 0.1
    ) -> float:
        """Get parameter with occasional exploration."""
        if name not in self.beliefs:
            raise KeyError(f"Unknown parameter: {name}")

        if random.random() < exploration_rate:
            return self.beliefs[name].sample()
        return self.beliefs[name].mean

    async def _log_parameter_change(
        self,
        name: str,
        old_value: float,
        new_value: float,
        reason: str,
    ) -> None:
        """Log parameter change for audit trail."""
        database = self._database
        if database is None:
            return

        try:
            async with aiosqlite.connect(database.db_file) as db:
                await db.execute("""
                    INSERT INTO parameter_history
                    (timestamp, coordinator_id, parameter_name,
                     old_value, new_value, reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    self.coordinator_id,
                    name,
                    old_value,
                    new_value,
                    reason,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.debug("Error logging parameter change: %s", e)
```

### Connecting to Anomaly Detection

When the pattern analyzer finds recurring anomalies, the parameter learner can adjust parameters to reduce them:

```python
async def update_from_anomaly_patterns(
    learner: BayesianParameterLearner,
    analyzer: PatternAnalyzer,
    coordinator_id: str,
    days: int = 30,
) -> Dict[str, float]:
    """Update parameters based on recurring anomaly patterns."""
    updates: Dict[str, float] = {}

    anomaly_patterns = await analyzer.analyze_anomaly_patterns(
        coordinator_id=coordinator_id, days=days
    )

    for pattern in anomaly_patterns:
        metric = pattern.get("metric_name", "")
        count = pattern.get("count", 0)
        avg_z = pattern.get("avg_z_score", 0)

        # Example: if presence sees recurring phantom occupancy anomalies,
        # reduce the decay timeout
        if (
            coordinator_id == "presence"
            and metric == "phantom_occupancy_rate"
            and count >= 5
        ):
            new_val = await learner.update_parameter(
                "decay_timeout_seconds",
                observation=learner.beliefs["decay_timeout_seconds"].mean * 0.85,
                weight=min(1.0, count / 10.0),
                reason=f"anomaly_pattern: {metric} count={count} avg_z={avg_z:.1f}",
            )
            if new_val is not None:
                updates["decay_timeout_seconds"] = new_val

        # Example: if energy sees recurring high import anomalies,
        # increase pre-cool aggressiveness
        if (
            coordinator_id == "energy"
            and metric == "grid_import_kwh_per_hour"
            and count >= 5
        ):
            new_val = await learner.update_parameter(
                "pre_cool_setpoint_offset",
                observation=learner.beliefs["pre_cool_setpoint_offset"].mean * 1.1,
                weight=min(1.0, count / 10.0),
                reason=f"anomaly_pattern: {metric} count={count} avg_z={avg_z:.1f}",
            )
            if new_val is not None:
                updates["pre_cool_setpoint_offset"] = new_val

    if updates:
        await learner.save_beliefs()

    return updates
```

---

## 9. DIAGNOSTIC SENSORS

### Architecture

v2 uses a **split approach**:

1. **Coordinator Manager** owns cross-cutting sensors that aggregate across all coordinators
2. **Each coordinator** owns domain-specific sensors

### Consistent State Vocabulary

All diagnostic sensors use a consistent vocabulary:

| Category | Values | Usage |
|----------|--------|-------|
| Severity | `"nominal"`, `"advisory"`, `"alert"`, `"critical"` | Anomaly and compliance sensors |
| Learning Status | `"insufficient_data"`, `"learning"`, `"active"`, `"paused"` | Learning and anomaly sensors |
| Compliance | `"full"`, `"partial"`, `"overridden"` | Compliance sensors |
| Effectiveness | `"excellent"`, `"good"`, `"fair"`, `"poor"`, `"insufficient_data"` | Effectiveness sensors |
| Enable State | `"enabled"`, `"disabled"` | When coordinator is disabled |

### Manager-Level Sensors (Cross-Cutting)

```yaml
# System-wide anomaly status
sensor.ura_system_anomaly:
  state: "nominal" | "advisory" | "alert" | "critical"
  attributes:
    active_anomalies: 0
    anomalies_today: 2
    worst_severity: "advisory"
    worst_coordinator: "presence"
    worst_metric: "room_transitions_per_hour"
    coordinators_with_anomalies: ["presence"]
    learning_status:
      presence: "active"
      energy: "learning"
      security: "insufficient_data"

# System-wide compliance status
sensor.ura_system_compliance:
  state: "full" | "partial" | "overridden"
  attributes:
    compliance_rate_today: 0.92
    compliance_rate_7day: 0.87
    overrides_today: 3
    override_sources: ["thermostat_manual", "app"]
    coordinators:
      presence: "full"
      energy: "partial"
      security: "full"
```

### Per-Coordinator Sensors

Each coordinator creates four diagnostic sensors:

```yaml
# 1. Situation sensor
sensor.ura_{coordinator_id}_situation:
  state: "{current_situation}"
  attributes:
    urgency: 0-100
    confidence: 0.0-1.0
    scope: "house"
    house_state: "home_day"
    last_decision_timestamp: "2026-02-28T16:30:00"

# 2. Anomaly sensor
sensor.ura_{coordinator_id}_anomaly:
  state: "nominal" | "advisory" | "alert" | "critical"
  attributes:
    learning_status: "active"
    active_anomalies: 0
    anomalies_today: 1
    worst_metric: ""
    worst_z_score: 0.0
    metrics:
      room_transitions_per_hour:
        mean: 3.2
        std: 1.1
        sample_count: 312
        active: true
      phantom_occupancy_rate:
        mean: 0.02
        std: 0.01
        sample_count: 312
        active: true

# 3. Compliance sensor
sensor.ura_{coordinator_id}_compliance:
  state: "full" | "partial" | "overridden"
  attributes:
    compliance_rate_today: 0.95
    compliance_rate_7day: 0.91
    override_count_today: 1
    override_sources: ["thermostat_manual"]
    devices_compliant: ["light.kitchen", "fan.kitchen"]
    devices_overridden: []

# 4. Effectiveness sensor
sensor.ura_{coordinator_id}_effectiveness:
  state: "excellent" | "good" | "fair" | "poor" | "insufficient_data"
  attributes:
    # Coordinator-specific metrics -- examples for Presence:
    transition_accuracy_7day: 0.94
    phantom_rate_7day: 0.02
    decay_effectiveness_7day: 0.91
    decisions_today: 45
    decisions_7day: 312
    learning_last_updated: "2026-02-28T03:00:00"
    parameters_adjusted_this_cycle: 2
    top_pattern: "Phantom occupancy 35% in room:closet during sleep"
```

### Sensor Implementation

```python
import logging
from typing import Any, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from ..const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)


class CoordinatorAnomalySensor(SensorEntity):
    """Per-coordinator anomaly diagnostic sensor."""

    _attr_entity_category = "diagnostic"

    def __init__(
        self,
        coordinator: "BaseCoordinator",
        anomaly_detector: AnomalyDetector,
    ) -> None:
        self._coordinator = coordinator
        self._anomaly_detector = anomaly_detector
        self._attr_name = f"URA {coordinator.name} Anomaly"
        self._attr_unique_id = (
            f"{DOMAIN}_{coordinator.coordinator_id}_anomaly"
        )
        self._attr_icon = "mdi:alert-circle"

    @property
    def device_info(self) -> DeviceInfo:
        return self._coordinator.device_info

    @property
    def native_value(self) -> str:
        """Return the worst active anomaly severity."""
        if not self._coordinator.enabled:
            return "disabled"

        status = self._anomaly_detector.get_learning_status()
        if status == "insufficient_data":
            return "insufficient_data"

        # Check for active anomalies (would be tracked in coordinator state)
        # Default to nominal
        return "nominal"

    @property
    def extra_state_attributes(self) -> dict:
        """Return anomaly detection details."""
        if not self._coordinator.enabled:
            return {"reason": "coordinator_disabled"}

        summary = self._anomaly_detector.get_status_summary()
        return {
            "learning_status": summary.get("learning_status", "unknown"),
            "minimum_samples": summary.get("minimum_samples", 0),
            "metrics": summary.get("metrics", {}),
        }


class CoordinatorComplianceSensor(SensorEntity):
    """Per-coordinator compliance diagnostic sensor."""

    _attr_entity_category = "diagnostic"

    def __init__(
        self,
        coordinator: "BaseCoordinator",
        compliance_tracker: ComplianceTracker,
    ) -> None:
        self._coordinator = coordinator
        self._compliance_tracker = compliance_tracker
        self._attr_name = f"URA {coordinator.name} Compliance"
        self._attr_unique_id = (
            f"{DOMAIN}_{coordinator.coordinator_id}_compliance"
        )
        self._attr_icon = "mdi:check-circle"
        self._cached_rate: float = 1.0

    @property
    def device_info(self) -> DeviceInfo:
        return self._coordinator.device_info

    @property
    def native_value(self) -> str:
        if not self._coordinator.enabled:
            return "disabled"
        if self._cached_rate >= 0.9:
            return "full"
        elif self._cached_rate >= 0.5:
            return "partial"
        return "overridden"

    async def async_update(self) -> None:
        """Update compliance rate from database."""
        if not self._coordinator.enabled:
            return
        self._cached_rate = await self._compliance_tracker.get_compliance_rate(
            coordinator_id=self._coordinator.coordinator_id,
            days=1,
        )


class SystemAnomalySensor(SensorEntity):
    """Manager-level cross-cutting anomaly sensor."""

    _attr_entity_category = "diagnostic"

    def __init__(self, manager: "CoordinatorManager") -> None:
        self._manager = manager
        self._attr_name = "URA System Anomaly"
        self._attr_unique_id = f"{DOMAIN}_system_anomaly"
        self._attr_icon = "mdi:alert-circle-outline"

    @property
    def device_info(self) -> DeviceInfo:
        return self._manager.device_info

    @property
    def native_value(self) -> str:
        """Return worst anomaly severity across all coordinators."""
        # Implementation would iterate over all coordinators'
        # anomaly detectors and return the worst severity
        return "nominal"
```

---

## 10. COORDINATOR ENABLE/DISABLE

### Purpose

Allow coordinators to be disabled without deletion. The Coordinator Manager is the authority for enable/disable state.

### Config Options

Each coordinator has a config option `CONF_{ID}_ENABLED`:

```python
# In const.py
CONF_PRESENCE_ENABLED: Final = "presence_coordinator_enabled"
CONF_ENERGY_ENABLED: Final = "energy_coordinator_enabled"
CONF_SECURITY_ENABLED: Final = "security_coordinator_enabled"
CONF_COMFORT_ENABLED: Final = "comfort_coordinator_enabled"
CONF_HVAC_ENABLED: Final = "hvac_coordinator_enabled"
```

### Manager Authority

The Manager reads config options and controls coordinator state:

```python
class CoordinatorManager:
    """Extended with enable/disable support."""

    async def async_set_coordinator_enabled(
        self,
        coordinator_id: str,
        enabled: bool,
    ) -> bool:
        """Enable or disable a coordinator.

        When disabling:
        - Set coordinator._enabled = False
        - Call coordinator._cancel_listeners() to unsubscribe
        - Sensors show "disabled"
        - evaluate() is skipped in batch processing

        When enabling:
        - Set coordinator._enabled = True
        - Call coordinator.async_setup() to re-register listeners
        - Sensors resume normal operation
        """
        coordinator = self._coordinators.get(coordinator_id)
        if coordinator is None:
            _LOGGER.warning(
                "Cannot enable/disable unknown coordinator: %s",
                coordinator_id,
            )
            return False

        if enabled == coordinator.enabled:
            return True  # No change needed

        if enabled:
            # Re-enable
            coordinator.enabled = True
            try:
                await coordinator.async_setup()
                _LOGGER.info("Coordinator %s re-enabled", coordinator_id)
            except Exception:
                _LOGGER.exception(
                    "Error re-enabling coordinator %s", coordinator_id
                )
                coordinator.enabled = False
                return False
        else:
            # Disable
            coordinator.enabled = False
            coordinator._cancel_listeners()
            _LOGGER.info("Coordinator %s disabled", coordinator_id)

        return True

    def get_coordinator_status(self, coordinator_id: str) -> dict:
        """Get status for a specific coordinator."""
        coordinator = self._coordinators.get(coordinator_id)
        if coordinator is None:
            return {"status": "not_registered"}

        return {
            "status": "enabled" if coordinator.enabled else "disabled",
            "coordinator_id": coordinator_id,
            "name": coordinator.name,
            "priority": coordinator.priority,
        }
```

### Behavior When Disabled

| Component | Behavior When Disabled |
|-----------|----------------------|
| `evaluate()` | Skipped by Manager (already implemented in `_async_process_batch`) |
| State listeners | Unsubscribed via `_cancel_listeners()` |
| Diagnostic sensors | All show `"disabled"` as state |
| Decision logging | No new decisions logged |
| Compliance tracking | No new checks scheduled |
| Anomaly detection | Paused, baselines preserved |
| Bayesian learning | Paused, beliefs preserved |
| Registration | Coordinator remains in `_coordinators` dict |

### Re-Enable Flow

```
User toggles CONF_{ID}_ENABLED to True
    |
    v
Manager.async_set_coordinator_enabled(id, True)
    |
    v
coordinator.enabled = True
    |
    v
coordinator.async_setup()
    - Re-registers state listeners
    - Loads baselines from DB
    - Loads parameter beliefs from DB
    |
    v
Sensors resume normal state reporting
    |
    v
Next intent batch includes this coordinator
```

---

## 11. DATABASE SCHEMA

### New and Updated Tables

v2 adds `scope` columns to existing tables and introduces new tables for anomaly detection and metric baselines.

```sql
-- v2: Updated decision_log with scope column
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'house',       -- v2: "house", "zone:X", "room:X"
    situation_classified TEXT,
    urgency INTEGER,
    confidence REAL,
    context_json TEXT NOT NULL,
    action_json TEXT NOT NULL,
    expected_savings_kwh REAL,
    expected_cost_savings REAL,
    expected_comfort_impact INTEGER,
    constraints_published TEXT,
    devices_commanded TEXT
);

CREATE INDEX IF NOT EXISTS idx_decision_timestamp ON decision_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_decision_coordinator ON decision_log(coordinator_id);
CREATE INDEX IF NOT EXISTS idx_decision_scope ON decision_log(scope);
CREATE INDEX IF NOT EXISTS idx_decision_situation ON decision_log(situation_classified);


-- v2: Updated compliance_log with scope column
CREATE TABLE IF NOT EXISTS compliance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    decision_id INTEGER,
    scope TEXT NOT NULL DEFAULT 'house',       -- v2: "house", "zone:X", "room:X"
    device_type TEXT NOT NULL,
    device_id TEXT NOT NULL,
    commanded_state TEXT NOT NULL,
    actual_state TEXT NOT NULL,
    compliant BOOLEAN NOT NULL,
    deviation_details TEXT,
    override_detected BOOLEAN,
    override_source TEXT,
    override_duration_minutes INTEGER,
    FOREIGN KEY (decision_id) REFERENCES decision_log(id)
);

CREATE INDEX IF NOT EXISTS idx_compliance_decision ON compliance_log(decision_id);
CREATE INDEX IF NOT EXISTS idx_compliance_timestamp ON compliance_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_compliance_scope ON compliance_log(scope);
CREATE INDEX IF NOT EXISTS idx_compliance_compliant ON compliance_log(compliant);


-- v2: Updated outcome_log -- generalized from energy-only
CREATE TABLE IF NOT EXISTS outcome_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'house',
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    decisions_in_period INTEGER,
    compliance_rate REAL,
    override_count INTEGER,
    metrics_json TEXT NOT NULL                  -- Coordinator-specific metrics as JSON
);

CREATE INDEX IF NOT EXISTS idx_outcome_coordinator ON outcome_log(coordinator_id);
CREATE INDEX IF NOT EXISTS idx_outcome_period ON outcome_log(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_outcome_scope ON outcome_log(scope);


-- v2 NEW: Anomaly log
CREATE TABLE IF NOT EXISTS anomaly_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    scope TEXT NOT NULL,                       -- "house", "zone:X", "room:X"
    metric_name TEXT NOT NULL,
    observed_value REAL NOT NULL,
    expected_mean REAL NOT NULL,
    expected_std REAL NOT NULL,
    z_score REAL NOT NULL,
    severity TEXT NOT NULL,                    -- "advisory", "alert", "critical"
    sample_size INTEGER NOT NULL,
    house_state TEXT,
    context_json TEXT,
    resolved BOOLEAN NOT NULL DEFAULT 0,
    resolution_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp ON anomaly_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_anomaly_coordinator ON anomaly_log(coordinator_id);
CREATE INDEX IF NOT EXISTS idx_anomaly_scope ON anomaly_log(scope);
CREATE INDEX IF NOT EXISTS idx_anomaly_severity ON anomaly_log(severity);
CREATE INDEX IF NOT EXISTS idx_anomaly_metric ON anomaly_log(metric_name);


-- v2 NEW: Metric baselines for anomaly detection
CREATE TABLE IF NOT EXISTS metric_baselines (
    coordinator_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    mean REAL NOT NULL,
    variance REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    last_updated TEXT,
    PRIMARY KEY (coordinator_id, metric_name, scope)
);


-- Existing: Bayesian parameter beliefs (unchanged)
CREATE TABLE IF NOT EXISTS parameter_beliefs (
    coordinator_id TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    mean REAL NOT NULL,
    std REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (coordinator_id, parameter_name)
);

-- Existing: Parameter change history (unchanged)
CREATE TABLE IF NOT EXISTS parameter_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    old_value REAL,
    new_value REAL NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_param_history
    ON parameter_history(coordinator_id, parameter_name);
CREATE INDEX IF NOT EXISTS idx_param_timestamp
    ON parameter_history(timestamp);


-- Existing: House state log (unchanged)
CREATE TABLE IF NOT EXISTS house_state_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    state TEXT NOT NULL,
    confidence REAL NOT NULL,
    trigger TEXT,
    previous_state TEXT
);

CREATE INDEX IF NOT EXISTS idx_house_state_timestamp
    ON house_state_log(timestamp);
```

### Migration from v1 Schema

To add the `scope` column to existing tables without data loss:

```python
async def migrate_v1_to_v2(database: "UniversalRoomDatabase") -> None:
    """Migrate diagnostics schema from v1 to v2."""
    try:
        async with aiosqlite.connect(database.db_file) as db:
            # Add scope to decision_log
            cursor = await db.execute("PRAGMA table_info(decision_log)")
            columns = {row[1] for row in await cursor.fetchall()}

            if "scope" not in columns:
                await db.execute(
                    "ALTER TABLE decision_log "
                    "ADD COLUMN scope TEXT NOT NULL DEFAULT 'house'"
                )

            # Add scope to compliance_log
            cursor = await db.execute("PRAGMA table_info(compliance_log)")
            columns = {row[1] for row in await cursor.fetchall()}

            if "scope" not in columns:
                await db.execute(
                    "ALTER TABLE compliance_log "
                    "ADD COLUMN scope TEXT NOT NULL DEFAULT 'house'"
                )

            # Create new tables
            await db.execute("""
                CREATE TABLE IF NOT EXISTS anomaly_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    coordinator_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    observed_value REAL NOT NULL,
                    expected_mean REAL NOT NULL,
                    expected_std REAL NOT NULL,
                    z_score REAL NOT NULL,
                    severity TEXT NOT NULL,
                    sample_size INTEGER NOT NULL,
                    house_state TEXT,
                    context_json TEXT,
                    resolved BOOLEAN NOT NULL DEFAULT 0,
                    resolution_notes TEXT
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS metric_baselines (
                    coordinator_id TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    mean REAL NOT NULL,
                    variance REAL NOT NULL,
                    sample_count INTEGER NOT NULL,
                    last_updated TEXT,
                    PRIMARY KEY (coordinator_id, metric_name, scope)
                )
            """)

            # Create generalized outcome_log if it does not exist
            # (v1 had energy-specific columns; v2 uses metrics_json)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS outcome_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    coordinator_id TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'house',
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    decisions_in_period INTEGER,
                    compliance_rate REAL,
                    override_count INTEGER,
                    metrics_json TEXT NOT NULL
                )
            """)

            # Create indexes
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_decision_scope ON decision_log(scope)",
                "CREATE INDEX IF NOT EXISTS idx_compliance_scope ON compliance_log(scope)",
                "CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp ON anomaly_log(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_anomaly_coordinator ON anomaly_log(coordinator_id)",
                "CREATE INDEX IF NOT EXISTS idx_anomaly_scope ON anomaly_log(scope)",
                "CREATE INDEX IF NOT EXISTS idx_anomaly_severity ON anomaly_log(severity)",
                "CREATE INDEX IF NOT EXISTS idx_anomaly_metric ON anomaly_log(metric_name)",
                "CREATE INDEX IF NOT EXISTS idx_outcome_coordinator ON outcome_log(coordinator_id)",
                "CREATE INDEX IF NOT EXISTS idx_outcome_scope ON outcome_log(scope)",
            ]:
                await db.execute(idx_sql)

            await db.commit()
            _LOGGER.info("Diagnostics schema migrated from v1 to v2")

    except Exception as e:
        _LOGGER.error("Error migrating diagnostics schema: %s", e)
```

### Data Retention

| Table | Retention | Rationale |
|-------|-----------|-----------|
| `decision_log` | 90 days | Matches `RETENTION_DECISION_LOG` in const.py |
| `compliance_log` | 90 days | Matches `RETENTION_COMPLIANCE_LOG` in const.py |
| `outcome_log` | 365 days | Long-term effectiveness tracking |
| `anomaly_log` | 90 days | Recent anomaly history |
| `metric_baselines` | Forever | Running statistics, never purged |
| `parameter_beliefs` | Forever | Current learned parameters |
| `parameter_history` | 365 days | Audit trail for parameter changes |
| `house_state_log` | 365 days | Matches `RETENTION_HOUSE_STATE_LOG` in const.py |

---

## 12. IMPLEMENTATION GUIDE

### Adding Full Diagnostics to a New Coordinator

```python
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from ..const import DOMAIN
from .base import BaseCoordinator, CoordinatorAction, Intent

_LOGGER = logging.getLogger(__name__)


class MyCoordinator(BaseCoordinator):
    """Example coordinator with full v2 diagnostics integration."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass=hass,
            coordinator_id="my_coordinator",
            name="My Coordinator",
            priority=50,
        )

        # Initialize diagnostics components
        self.decision_logger = DecisionLogger(hass)
        self.compliance_tracker = ComplianceTracker(hass)
        self.outcome_measurer = OutcomeMeasurer(hass)
        self.pattern_analyzer = PatternAnalyzer(hass)

        # Anomaly detection with coordinator-specific metrics
        self.anomaly_detector = AnomalyDetector(
            hass=hass,
            coordinator_id=self.coordinator_id,
            metric_names=[
                "decisions_per_hour",
                "override_rate",
            ],
            minimum_samples=48,
        )

        # Bayesian parameter learning
        self.parameter_learner = BayesianParameterLearner(
            hass=hass,
            coordinator_id=self.coordinator_id,
            default_beliefs={
                "my_threshold": ParameterBelief(
                    mean=10.0, std=2.0, min_value=1.0, max_value=50.0
                ),
                "my_timeout": ParameterBelief(
                    mean=300.0, std=60.0, min_value=60.0, max_value=900.0
                ),
            },
        )

    async def async_setup(self) -> None:
        """Set up coordinator and load persisted state."""
        # Load persisted anomaly baselines and parameter beliefs
        await self.anomaly_detector.load_baselines()
        await self.parameter_learner.load_beliefs()

        # Schedule domain-specific learning (weekly for this example)
        self._unsub_listeners.append(
            async_track_time_interval(
                self.hass,
                self._learning_cycle,
                timedelta(days=7),
            )
        )

        _LOGGER.info("MyCoordinator setup complete")

    async def evaluate(
        self,
        intents: List[Intent],
        context: Dict[str, Any],
    ) -> List[CoordinatorAction]:
        """Evaluate intents with full diagnostics."""

        # 1. Get learned parameters
        params = self.parameter_learner.get_parameters()
        threshold = params.get("my_threshold", 10.0)

        # 2. Classify situation
        scope = "house"
        situation = "nominal"
        # ... coordinator-specific logic ...

        # 3. Log decision
        decision_id = await self.decision_logger.log_decision(DecisionLog(
            timestamp=datetime.utcnow(),
            coordinator_id=self.coordinator_id,
            decision_type="evaluation",
            scope=scope,
            situation_classified=situation,
            urgency=30,
            confidence=0.85,
            context={
                "house_state": str(context.get("house_state")),
                "threshold": threshold,
            },
            action={"type": "adjust", "value": threshold},
        ))

        # 4. Record observation for anomaly detection
        anomaly = self.anomaly_detector.record_observation(
            metric_name="decisions_per_hour",
            scope=scope,
            value=float(len(intents)),
        )
        if anomaly is not None:
            anomaly.house_state = str(context.get("house_state", ""))
            await self.anomaly_detector.store_anomaly(anomaly)

        # 5. Build actions
        actions: List[CoordinatorAction] = []
        # ... coordinator-specific action generation ...

        # 6. Schedule compliance check for each device action
        for action in actions:
            if decision_id and action.target_device:
                await self.compliance_tracker.schedule_check(
                    decision_id=decision_id,
                    scope=scope,
                    device_type="light",  # or whatever device type
                    device_id=action.target_device,
                    commanded_state={"state": "on"},
                )

        return actions

    async def _learning_cycle(self, _now: Any = None) -> None:
        """Periodic learning cycle -- adjust parameters from data."""
        # Analyze override patterns
        patterns = await self.pattern_analyzer.analyze_override_patterns(
            coordinator_id=self.coordinator_id, days=7
        )

        # Update parameters from anomaly patterns
        updates = await update_from_anomaly_patterns(
            learner=self.parameter_learner,
            analyzer=self.pattern_analyzer,
            coordinator_id=self.coordinator_id,
            days=30,
        )

        if updates:
            _LOGGER.info(
                "%s learning cycle updated parameters: %s",
                self.coordinator_id,
                updates,
            )

    async def async_teardown(self) -> None:
        """Tear down -- persist state."""
        await self.anomaly_detector.save_baselines()
        await self.parameter_learner.save_beliefs()
        self._cancel_listeners()
```

### Registering Diagnostic Sensors

```python
async def async_setup_coordinator_sensors(
    hass: HomeAssistant,
    coordinator: BaseCoordinator,
    anomaly_detector: AnomalyDetector,
    compliance_tracker: ComplianceTracker,
    async_add_entities,
) -> None:
    """Set up diagnostic sensors for a coordinator."""
    sensors = [
        CoordinatorAnomalySensor(coordinator, anomaly_detector),
        CoordinatorComplianceSensor(coordinator, compliance_tracker),
        # Add situation and effectiveness sensors similarly
    ]
    async_add_entities(sensors)


async def async_setup_manager_sensors(
    hass: HomeAssistant,
    manager: "CoordinatorManager",
    async_add_entities,
) -> None:
    """Set up manager-level diagnostic sensors."""
    sensors = [
        SystemAnomalySensor(manager),
        # SystemComplianceSensor(manager),
    ]
    async_add_entities(sensors)
```

---

## 13. COORDINATOR-SPECIFIC EXTENSIONS

### Presence Coordinator

**Outcome Metrics:**
- `room_transitions`: Total transitions in period
- `phantom_occupancy_events`: Rooms marked occupied with nobody there
- `missed_occupancy_events`: Rooms occupied but not detected
- `transition_accuracy`: Correct transitions / total
- `avg_detection_latency_seconds`: Time from physical entry to detection
- `decay_timeout_effectiveness`: Correct timeout expirations / total

**Anomaly Metrics:**
- `room_transitions_per_hour`: Unusually high/low movement
- `phantom_occupancy_rate`: Rising rate of false occupancy
- `avg_occupancy_duration_minutes`: Abnormal room dwell times
- `simultaneous_rooms_occupied`: More rooms occupied than persons tracked

**Learnable Parameters:**

```python
PRESENCE_DEFAULT_BELIEFS = {
    "decay_timeout_seconds": ParameterBelief(
        mean=300.0, std=60.0, min_value=60.0, max_value=900.0
    ),
    "motion_confidence_weight": ParameterBelief(
        mean=0.6, std=0.1, min_value=0.1, max_value=1.0
    ),
    "mmwave_confidence_weight": ParameterBelief(
        mean=0.9, std=0.1, min_value=0.3, max_value=1.0
    ),
    "phantom_threshold": ParameterBelief(
        mean=0.05, std=0.02, min_value=0.01, max_value=0.2
    ),
}
```

**Learning Schedule:** Daily (occupancy patterns shift frequently)

**Diagnostic Sensors:**

```yaml
sensor.ura_presence_situation:
  state: "tracking"  # or "degraded", "blind_spot"
  attributes:
    rooms_monitored: 8
    persons_tracked: 3
    active_occupancies: 2
    scope: "house"

sensor.ura_presence_anomaly:
  state: "nominal"
  attributes:
    learning_status: "active"
    metrics:
      room_transitions_per_hour:
        mean: 3.2
        std: 1.1
        sample_count: 720
        active: true

sensor.ura_presence_compliance:
  state: "full"
  attributes:
    compliance_rate_today: 1.0
    # Presence rarely commands devices directly,
    # but tracks light/fan compliance on occupancy changes

sensor.ura_presence_effectiveness:
  state: "good"
  attributes:
    transition_accuracy_7day: 0.94
    phantom_rate_7day: 0.02
    decay_effectiveness_7day: 0.91
```

### Security Coordinator

**Outcome Metrics:**
- `alerts_generated`: Total alerts in period
- `true_positives`: Confirmed real alerts
- `false_positives`: Alerts that were not real threats
- `false_negatives`: Missed threats (detected post-hoc)
- `alert_accuracy`: true_positives / (true_positives + false_positives)
- `avg_response_time_seconds`: Time from alert to user acknowledgment
- `perimeter_events`: Door/window events during alert hours
- `door_open_violations`: Doors left open beyond threshold
- `window_open_violations`: Windows left open beyond threshold

**Anomaly Metrics:**
- `door_events_per_hour`: Unusual door activity
- `window_events_per_hour`: Unusual window activity
- `perimeter_alerts_per_day`: Spike in perimeter alerts
- `after_hours_activity_count`: Activity during away/sleep states

**Learnable Parameters:**

```python
SECURITY_DEFAULT_BELIEFS = {
    "door_alert_threshold_minutes": ParameterBelief(
        mean=10.0, std=3.0, min_value=1.0, max_value=30.0
    ),
    "window_alert_threshold_minutes": ParameterBelief(
        mean=30.0, std=10.0, min_value=5.0, max_value=120.0
    ),
    "sleep_door_alert_threshold_minutes": ParameterBelief(
        mean=1.0, std=0.5, min_value=0.5, max_value=5.0
    ),
    "perimeter_alert_sensitivity": ParameterBelief(
        mean=0.7, std=0.1, min_value=0.3, max_value=1.0
    ),
}
```

**Learning Schedule:** Monthly (security baseline events are rare, need more data per cycle)

**Diagnostic Sensors:**

```yaml
sensor.ura_security_situation:
  state: "secure"  # or "alert", "breach", "monitoring"
  attributes:
    open_doors: 0
    open_windows: 1
    perimeter_status: "secure"
    scope: "house"

sensor.ura_security_anomaly:
  state: "nominal"
  attributes:
    learning_status: "learning"  # Security needs 168 samples
    metrics:
      door_events_per_hour:
        mean: 1.2
        std: 0.8
        sample_count: 96
        active: false  # Not yet at 168 minimum

sensor.ura_security_compliance:
  state: "full"
  attributes:
    compliance_rate_today: 1.0
    door_violations_today: 0
    window_violations_today: 0

sensor.ura_security_effectiveness:
  state: "insufficient_data"
  attributes:
    alerts_7day: 2
    false_positive_rate_7day: 0.0
    avg_response_time_7day: 45.2
```

### Energy Coordinator

**Outcome Metrics:**
- `import_kwh`: Grid import in period
- `export_kwh`: Grid export in period
- `solar_production_kwh`: Solar production
- `battery_discharge_kwh`: Battery discharge
- `actual_cost`: Total energy cost
- `baseline_cost`: Cost without optimization
- `savings`: baseline_cost - actual_cost
- `solar_predicted_kwh` / `solar_error_pct`: Forecast accuracy
- `load_predicted_kwh` / `load_error_pct`: Load forecast accuracy
- `tou_period`: Which TOU period this outcome covers

**Anomaly Metrics:**
- `grid_import_kwh_per_hour`: Unexpectedly high grid draw
- `solar_production_kwh_per_hour`: Solar production anomalies (panel issues)
- `baseline_cost_deviation_pct`: Cost deviating from expected baseline
- `battery_efficiency_ratio`: Battery round-trip efficiency anomalies

**Learnable Parameters:**

```python
ENERGY_DEFAULT_BELIEFS = {
    "coast_setpoint_offset": ParameterBelief(
        mean=3.0, std=0.5, min_value=0.5, max_value=6.0
    ),
    "pre_cool_setpoint_offset": ParameterBelief(
        mean=-3.0, std=0.5, min_value=-6.0, max_value=-0.5
    ),
    "pre_cool_window_minutes": ParameterBelief(
        mean=60.0, std=15.0, min_value=15.0, max_value=120.0
    ),
    "export_soc_threshold": ParameterBelief(
        mean=60.0, std=10.0, min_value=20.0, max_value=90.0
    ),
    "solar_forecast_multiplier": ParameterBelief(
        mean=1.0, std=0.1, min_value=0.5, max_value=1.5
    ),
}
```

**Learning Schedule:** Weekly (TOU patterns are stable week-to-week)

**Diagnostic Sensors:**

```yaml
sensor.ura_energy_situation:
  state: "EXPENSIVE"  # or "CHEAP", "EXPORTING", "PRE_CONDITION", "COAST"
  attributes:
    urgency: 70
    confidence: 0.85
    tou_period: "peak"
    scope: "house"

sensor.ura_energy_anomaly:
  state: "advisory"
  attributes:
    learning_status: "active"
    active_anomalies: 1
    worst_metric: "grid_import_kwh_per_hour"
    worst_z_score: 2.3
    metrics:
      grid_import_kwh_per_hour:
        mean: 2.1
        std: 0.8
        sample_count: 720
        active: true

sensor.ura_energy_compliance:
  state: "partial"
  attributes:
    compliance_rate_today: 0.78
    compliance_rate_7day: 0.82
    override_count_today: 3
    override_sources: ["thermostat_manual", "thermostat_manual", "app"]

sensor.ura_energy_effectiveness:
  state: "good"
  attributes:
    savings_today: 2.45
    savings_7day: 15.80
    savings_vs_baseline_pct: 23.5
    solar_forecast_accuracy_7day: 0.88
    parameters_adjusted_this_week: 2
    top_pattern: "HVAC coast overridden 73% when outdoor > 95 F"
```

### Comfort Coordinator

**Outcome Metrics:**
- `comfort_score_avg`: Average comfort score (0-100) in period
- `time_in_comfort_zone_minutes`: Minutes within comfort bounds
- `time_outside_comfort_zone_minutes`: Minutes outside bounds
- `comfort_violations`: Number of rooms exceeding bounds
- `max_temp_deviation`: Worst temperature deviation from setpoint
- `max_humidity_deviation`: Worst humidity deviation from range
- `override_count`: Manual comfort adjustments

**Anomaly Metrics:**
- `comfort_score_hourly`: Comfort score drops
- `violations_per_hour`: Spike in comfort violations
- `override_rate_per_day`: Rising override frequency

**Learnable Parameters:**

```python
COMFORT_DEFAULT_BELIEFS = {
    "comfort_temp_min": ParameterBelief(
        mean=68.0, std=1.0, min_value=60.0, max_value=75.0
    ),
    "comfort_temp_max": ParameterBelief(
        mean=76.0, std=1.0, min_value=72.0, max_value=85.0
    ),
    "comfort_humidity_min": ParameterBelief(
        mean=30.0, std=5.0, min_value=15.0, max_value=45.0
    ),
    "comfort_humidity_max": ParameterBelief(
        mean=60.0, std=5.0, min_value=45.0, max_value=80.0
    ),
}
```

**Learning Schedule:** Weekly

### HVAC Coordinator

**Outcome Metrics:**
- `efficiency_ratio`: Actual cooling/heating achieved vs energy consumed
- `runtime_minutes`: Total HVAC runtime in period
- `runtime_vs_target_pct`: Actual runtime as percentage of predicted needed
- `zone_balance_score`: How evenly zones are conditioned (0-1)
- `pre_cool_effectiveness`: Temperature retained after pre-cool (degrees)
- `fan_coordination_activations`: How often fan assist was used

**Anomaly Metrics:**
- `runtime_per_degree_day`: HVAC running longer than expected for conditions
- `zone_imbalance_score`: Zones diverging more than normal
- `short_cycle_count`: Rapid on/off cycling (compressor stress)
- `setpoint_deviation_avg`: Zones not reaching setpoint

**Learnable Parameters:**

```python
HVAC_DEFAULT_BELIEFS = {
    "pre_cool_lead_minutes": ParameterBelief(
        mean=60.0, std=15.0, min_value=15.0, max_value=120.0
    ),
    "coast_duration_minutes": ParameterBelief(
        mean=45.0, std=10.0, min_value=15.0, max_value=90.0
    ),
    "fan_assist_threshold_degrees": ParameterBelief(
        mean=2.0, std=0.5, min_value=0.5, max_value=5.0
    ),
    "zone_balance_tolerance_degrees": ParameterBelief(
        mean=2.0, std=0.5, min_value=0.5, max_value=5.0
    ),
}
```

**Learning Schedule:** Weekly (thermal dynamics change seasonally, weekly captures enough variation)

---

## 14. QUICK REFERENCE

### Key Tables

| Table | Purpose | Retention | v2 Changes |
|-------|---------|-----------|------------|
| `decision_log` | Every coordinator decision | 90 days | Added `scope` column |
| `compliance_log` | Commanded vs actual state | 90 days | Added `scope` column |
| `outcome_log` | Period-level measurements | 1 year | Generalized with `metrics_json` |
| `anomaly_log` | Detected anomalies | 90 days | NEW |
| `metric_baselines` | Running statistics per metric | Forever | NEW |
| `parameter_beliefs` | Current learned parameters | Forever | Unchanged |
| `parameter_history` | Parameter change audit trail | 1 year | Unchanged |

### Key Metrics

| Metric | Good | Fair | Poor |
|--------|------|------|------|
| Compliance Rate | > 80% | 50-80% | < 50% |
| Anomaly Rate | < 1/day | 1-3/day | > 3/day |
| Prediction Accuracy | > 85% | 70-85% | < 70% |
| Comfort Violations/Day | < 1 | 1-3 | > 3 |

### Severity Vocabulary

| Level | Z-Score Range | Meaning |
|-------|--------------|---------|
| `nominal` | < 2.0 | Within normal variation |
| `advisory` | 2.0 - 3.0 | Unusual but not alarming |
| `alert` | 3.0 - 4.0 | Significant deviation |
| `critical` | > 4.0 | Extreme deviation |

### Learning Schedule

| Coordinator | Outcome Measurement | Pattern/Learning | Min Samples |
|-------------|--------------------|--------------------|-------------|
| Energy | Per TOU period | Weekly | 48 |
| Presence | Hourly | Daily | 24 |
| Security | Daily | Monthly | 168 |
| Comfort | Hourly | Weekly | 48 |
| HVAC | Per HVAC cycle | Weekly | 48 |

### Sensor Naming Convention

| Sensor | Entity ID Pattern |
|--------|------------------|
| Coordinator Situation | `sensor.ura_{coordinator_id}_situation` |
| Coordinator Anomaly | `sensor.ura_{coordinator_id}_anomaly` |
| Coordinator Compliance | `sensor.ura_{coordinator_id}_compliance` |
| Coordinator Effectiveness | `sensor.ura_{coordinator_id}_effectiveness` |
| System Anomaly | `sensor.ura_system_anomaly` |
| System Compliance | `sensor.ura_system_compliance` |

### Scope Values

| Scope | Format | Example |
|-------|--------|---------|
| House-level | `"house"` | `"house"` |
| Zone-level | `"zone:{name}"` | `"zone:upstairs"` |
| Room-level | `"room:{name}"` | `"room:master_bedroom"` |

---

**Document Status:** Design Complete
**Version:** 2.0
**Applies To:** All URA Domain Coordinators
**Database:** Shared SQLite via aiosqlite (existing URA database.py pattern)
**Replaces:** COORDINATOR_DIAGNOSTICS_FRAMEWORK.md v1.0
