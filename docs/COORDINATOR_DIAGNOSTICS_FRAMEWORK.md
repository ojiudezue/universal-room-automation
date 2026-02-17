# COORDINATOR DIAGNOSTICS FRAMEWORK

**Version:** 1.0  
**Status:** Design Complete  
**Last Updated:** 2026-01-24  
**Applies To:** All URA Domain Coordinators

---

## TABLE OF CONTENTS

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Decision Logging](#3-decision-logging)
4. [Compliance Tracking](#4-compliance-tracking)
5. [Outcome Measurement](#5-outcome-measurement)
6. [Pattern Analysis](#6-pattern-analysis)
7. [Bayesian Parameter Learning](#7-bayesian-parameter-learning)
8. [Diagnostic Sensors](#8-diagnostic-sensors)
9. [Database Schema](#9-database-schema)
10. [Implementation Guide](#10-implementation-guide)
11. [Coordinator-Specific Extensions](#11-coordinator-specific-extensions)

---

## 1. OVERVIEW

### The Problem

Coordinators make decisions based on predictions and rules, but reality intervenes:

| Challenge | Example |
|-----------|---------|
| **Human overrides** | Someone cranks the AC during peak TOU |
| **Prediction misses** | Solar forecast was wrong by 20% |
| **Condition drift** | House thermal characteristics change seasonally |
| **No feedback loop** | Without measurement, we can't prove savings or improve |

### The Solution: Observe → Audit → Learn → Adapt

This framework provides a **reusable pattern** for all coordinators to:

1. **Log** every decision with full context
2. **Track** compliance (actual vs commanded state)
3. **Measure** outcomes (did it work? savings? comfort?)
4. **Analyze** patterns (when/why do overrides happen?)
5. **Adapt** parameters through Bayesian learning

### Framework Benefits

| Benefit | Description |
|---------|-------------|
| **Transparency** | Know exactly why decisions were made |
| **Override Detection** | Understand when/why humans intervene |
| **Effectiveness Measurement** | Prove actual $ savings |
| **Self-Optimization** | Parameters improve without manual tuning |
| **Debugging** | Trace decision chains when things go wrong |

---

## 2. ARCHITECTURE

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                COORDINATOR DIAGNOSTICS & LEARNING SYSTEM                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   REAL-TIME LAYER (Every Decision)                                          │
│  ┌───────────────┐     ┌───────────────┐                                    │
│  │   DECISION    │────▶│  COMPLIANCE   │                                    │
│  │    LOGGING    │     │   TRACKING    │                                    │
│  │               │     │               │                                    │
│  │ Full context  │     │ Commanded vs  │                                    │
│  │ for every     │     │ actual state  │                                    │
│  │ action taken  │     │ after delay   │                                    │
│  └───────────────┘     └───────────────┘                                    │
│                                                                              │
│   PERIODIC LAYER (Per TOU Period / Daily)                                   │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      OUTCOME MEASUREMENT                               │  │
│  │                                                                        │  │
│  │   Energy: import_kwh, export_kwh, savings vs baseline                 │  │
│  │   Comfort: violations, max_deviation, override_count                  │  │
│  │   Predictions: solar_error, load_error, occupancy_accuracy            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│   ANALYSIS LAYER (Weekly / Monthly)                                          │
│  ┌───────────────┐     ┌───────────────┐                                    │
│  │    PATTERN    │────▶│   BAYESIAN    │                                    │
│  │   ANALYSIS    │     │   LEARNING    │                                    │
│  │               │     │               │                                    │
│  │ Override      │     │ Parameter     │                                    │
│  │ patterns,     │     │ adjustment    │                                    │
│  │ drift detect  │     │ from data     │                                    │
│  └───────────────┘     └───────────────┘                                    │
│                               │                                              │
│                               ▼                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    COORDINATOR PARAMETERS                              │  │
│  │                                                                        │  │
│  │   coast_offset: 3.0°F → 2.5°F (learned from override patterns)        │  │
│  │   solar_multiplier: 1.0 → 0.88 (learned from forecast errors)         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Frequency | Purpose |
|-----------|-----------|---------|
| Decision Logging | Every action | Full audit trail |
| Compliance Tracking | 2 min after action | Detect overrides |
| Outcome Measurement | Per TOU period | Measure effectiveness |
| Pattern Analysis | Weekly | Find recurring patterns |
| Bayesian Learning | Weekly | Adjust parameters |

---

## 3. DECISION LOGGING

### Purpose

Record **every coordinator decision** with full context for later analysis.

### Data Structure

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class DecisionLog:
    """Record of a coordinator decision."""
    
    # Identity
    timestamp: datetime
    coordinator_id: str           # "energy", "hvac", "lighting", "pool"
    decision_type: str            # "tou_transition", "constraint_update", etc.
    
    # Classification
    situation_classified: str     # "EXPENSIVE", "PRE_CONDITION", etc.
    urgency: int                  # 0-100
    confidence: float             # 0.0-1.0
    
    # Inputs (everything that informed the decision)
    context: dict[str, Any]       # Full context snapshot
    
    # Action taken
    action: dict[str, Any]        # Full action details
    
    # Predictions (for later validation)
    expected_savings_kwh: float | None = None
    expected_cost_savings: float | None = None
    expected_comfort_impact: int | None = None  # 0-10 scale
    
    # Downstream effects
    constraints_published: list[str] = field(default_factory=list)
    devices_commanded: list[str] = field(default_factory=list)
```

### Implementation

```python
import json
import sqlite3
from pathlib import Path

class DecisionLogger:
    """Log decisions to SQLite for analysis."""
    
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db = sqlite3.connect(str(self.db_path))
        self._ensure_schema()
    
    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS decision_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                coordinator_id TEXT NOT NULL,
                decision_type TEXT NOT NULL,
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
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_decision_timestamp ON decision_log(timestamp)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_decision_coordinator ON decision_log(coordinator_id)"
        )
        self.db.commit()
    
    async def log_decision(self, decision: DecisionLog) -> int:
        """Log a decision and return its ID."""
        cursor = self.db.execute("""
            INSERT INTO decision_log 
            (timestamp, coordinator_id, decision_type, situation_classified,
             urgency, confidence, context_json, action_json,
             expected_savings_kwh, expected_cost_savings, expected_comfort_impact,
             constraints_published, devices_commanded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision.timestamp.isoformat(),
            decision.coordinator_id,
            decision.decision_type,
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
        self.db.commit()
        return cursor.lastrowid
    
    def get_decisions(
        self,
        coordinator_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve decisions with optional filters."""
        query = "SELECT * FROM decision_log WHERE 1=1"
        params = []
        
        if coordinator_id:
            query += " AND coordinator_id = ?"
            params.append(coordinator_id)
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())
        
        query += f" ORDER BY timestamp DESC LIMIT {limit}"
        
        cursor = self.db.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
```

### Usage in Coordinators

```python
class EnergyCoordinator:
    """Example integration of decision logging."""
    
    def __init__(self, hass, event_bus, db_path):
        self.decision_logger = DecisionLogger(db_path)
        # ...
    
    async def _decision_cycle(self) -> None:
        """Main decision cycle with logging."""
        # Gather context
        ctx = await self._gather_context()
        
        # Make decision
        situation = self._classifier.classify(ctx)
        actions = self._action_generator.generate(situation, ctx)
        
        # LOG THE DECISION
        decision_id = await self.decision_logger.log_decision(DecisionLog(
            timestamp=datetime.now(),
            coordinator_id="energy",
            decision_type="decision_cycle",
            situation_classified=situation.name,
            urgency=situation.urgency,
            confidence=0.85,  # Could be calculated
            context=asdict(ctx),
            action={
                "battery": asdict(actions.battery) if actions.battery else None,
                "hvac": asdict(actions.hvac) if actions.hvac else None,
                "pool": asdict(actions.pool) if actions.pool else None,
            },
            expected_savings_kwh=self._estimate_savings(actions),
            devices_commanded=[
                d for d in ["battery", "pool", "evse_a", "evse_b"]
                if getattr(actions, d, None)
            ],
        ))
        
        # Execute actions
        await self._execute_actions(actions)
        
        # Schedule compliance check
        await self.compliance_tracker.schedule_check(decision_id, actions)
```

---

## 4. COMPLIANCE TRACKING

### Purpose

Track whether devices **actually followed** commands, detecting human overrides.

### Data Structure

```python
@dataclass
class ComplianceRecord:
    """Track actual vs commanded state."""
    
    timestamp: datetime
    decision_id: int              # Links to decision_log
    
    device_type: str              # "hvac_zone", "battery", "pool", "evse"
    device_id: str                # Entity ID
    
    # What was commanded
    commanded_state: dict[str, Any]
    
    # What actually happened
    actual_state: dict[str, Any]
    
    # Analysis
    compliant: bool
    deviation_details: dict | None = None
    
    # Override detection
    override_detected: bool = False
    override_source: str | None = None   # "manual", "app", "schedule", "automation"
    override_duration_minutes: int | None = None
```

### Implementation

```python
import asyncio
from homeassistant.core import HomeAssistant

class ComplianceTracker:
    """Track compliance with coordinator commands."""
    
    COMPLIANCE_CHECK_DELAY = 120  # Seconds to wait before checking
    
    def __init__(self, hass: HomeAssistant, db_path: str):
        self.hass = hass
        self.db = sqlite3.connect(db_path)
        self._ensure_schema()
    
    def _ensure_schema(self) -> None:
        """Create compliance_log table."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS compliance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                decision_id INTEGER,
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
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_compliance_decision ON compliance_log(decision_id)"
        )
        self.db.commit()
    
    async def schedule_check(
        self,
        decision_id: int,
        device_type: str,
        device_id: str,
        commanded_state: dict,
    ) -> None:
        """Schedule a compliance check after command execution."""
        
        async def _delayed_check():
            await asyncio.sleep(self.COMPLIANCE_CHECK_DELAY)
            await self._check_compliance(
                decision_id, device_type, device_id, commanded_state
            )
        
        asyncio.create_task(_delayed_check())
    
    async def _check_compliance(
        self,
        decision_id: int,
        device_type: str,
        device_id: str,
        commanded_state: dict,
    ) -> ComplianceRecord:
        """Check if device complied with command."""
        
        # Get current state
        state = self.hass.states.get(device_id)
        actual_state = self._extract_state(state, device_type)
        
        # Compare
        compliant, deviation = self._compare_states(
            commanded_state, actual_state, device_type
        )
        
        # Detect override source
        override_source = None
        if not compliant:
            override_source = await self._detect_override_source(
                device_id, device_type
            )
        
        record = ComplianceRecord(
            timestamp=datetime.now(),
            decision_id=decision_id,
            device_type=device_type,
            device_id=device_id,
            commanded_state=commanded_state,
            actual_state=actual_state,
            compliant=compliant,
            deviation_details=deviation,
            override_detected=not compliant,
            override_source=override_source,
        )
        
        # Store
        self._store_compliance(record)
        
        return record
    
    def _compare_states(
        self,
        commanded: dict,
        actual: dict,
        device_type: str,
    ) -> tuple[bool, dict | None]:
        """Compare commanded vs actual state."""
        
        if device_type == "hvac_zone":
            # Check setpoint within tolerance
            cmd_setpoint = commanded.get("target_temp_high")
            act_setpoint = actual.get("target_temp_high")
            
            if cmd_setpoint and act_setpoint:
                if abs(cmd_setpoint - act_setpoint) > 1.0:  # 1°F tolerance
                    return False, {
                        "field": "target_temp_high",
                        "commanded": cmd_setpoint,
                        "actual": act_setpoint,
                        "delta": act_setpoint - cmd_setpoint,
                    }
            
            # Check preset mode
            cmd_preset = commanded.get("preset_mode")
            act_preset = actual.get("preset_mode")
            if cmd_preset and act_preset and cmd_preset != act_preset:
                return False, {
                    "field": "preset_mode",
                    "commanded": cmd_preset,
                    "actual": act_preset,
                }
        
        elif device_type in ["pool", "evse"]:
            # Simple on/off check
            cmd_on = commanded.get("state") == "on"
            act_on = actual.get("state") == "on"
            if cmd_on != act_on:
                return False, {
                    "field": "state",
                    "commanded": "on" if cmd_on else "off",
                    "actual": "on" if act_on else "off",
                }
        
        elif device_type == "battery":
            # Check mode
            cmd_mode = commanded.get("mode")
            act_mode = actual.get("mode")
            if cmd_mode and act_mode and cmd_mode != act_mode:
                return False, {
                    "field": "mode",
                    "commanded": cmd_mode,
                    "actual": act_mode,
                }
        
        return True, None
    
    async def _detect_override_source(
        self,
        device_id: str,
        device_type: str,
    ) -> str:
        """Attempt to detect what caused the override."""
        
        if device_type == "hvac_zone":
            # Carrier Infinity sets preset_mode to "manual" on user touch
            state = self.hass.states.get(device_id)
            if state and state.attributes.get("preset_mode") == "manual":
                return "thermostat_manual"
        
        # Could check logbook for recent changes
        # Could check context.user_id if available
        
        return "unknown"
    
    def _extract_state(self, state, device_type: str) -> dict:
        """Extract relevant state based on device type."""
        if not state:
            return {}
        
        if device_type == "hvac_zone":
            return {
                "hvac_mode": state.state,
                "preset_mode": state.attributes.get("preset_mode"),
                "target_temp_high": state.attributes.get("target_temp_high"),
                "target_temp_low": state.attributes.get("target_temp_low"),
            }
        elif device_type in ["pool", "evse"]:
            return {"state": state.state}
        elif device_type == "battery":
            return {"mode": state.attributes.get("storage_mode")}
        
        return {"state": state.state}
    
    def _store_compliance(self, record: ComplianceRecord) -> None:
        """Store compliance record in database."""
        self.db.execute("""
            INSERT INTO compliance_log
            (timestamp, decision_id, device_type, device_id,
             commanded_state, actual_state, compliant, deviation_details,
             override_detected, override_source, override_duration_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.timestamp.isoformat(),
            record.decision_id,
            record.device_type,
            record.device_id,
            json.dumps(record.commanded_state),
            json.dumps(record.actual_state),
            record.compliant,
            json.dumps(record.deviation_details) if record.deviation_details else None,
            record.override_detected,
            record.override_source,
            record.override_duration_minutes,
        ))
        self.db.commit()
    
    def get_compliance_rate(
        self,
        coordinator_id: str | None = None,
        days: int = 7,
    ) -> float:
        """Get compliance rate for recent period."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        query = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN compliant THEN 1 ELSE 0 END) as compliant_count
            FROM compliance_log
            WHERE timestamp >= ?
        """
        
        cursor = self.db.execute(query, (cutoff,))
        row = cursor.fetchone()
        
        if row and row[0] > 0:
            return row[1] / row[0]
        return 1.0  # No data = assume compliant
```

---

## 5. OUTCOME MEASUREMENT

### Purpose

Measure **actual results** after each TOU period to validate effectiveness.

### Data Structure

```python
@dataclass
class OutcomeMeasurement:
    """Measured outcomes for a time period."""
    
    period_start: datetime
    period_end: datetime
    tou_period: str               # "off_peak", "mid_peak", "peak"
    
    # Energy outcomes
    import_kwh: float
    export_kwh: float
    solar_production_kwh: float
    battery_discharge_kwh: float
    
    # Cost outcomes
    actual_cost: float
    baseline_cost: float          # Without optimization
    savings: float
    
    # Comfort outcomes
    comfort_violations: int       # Rooms exceeding bounds
    max_temp_deviation: float     # Worst case
    rooms_exceeded: list[str]
    manual_overrides: int
    
    # Prediction accuracy
    solar_predicted: float
    solar_actual: float
    solar_error_pct: float
    
    load_predicted: float
    load_actual: float
    load_error_pct: float
```

### Implementation

```python
class OutcomeMeasurer:
    """Measure and record outcomes for analysis."""
    
    def __init__(self, hass: HomeAssistant, db_path: str):
        self.hass = hass
        self.db = sqlite3.connect(db_path)
        self._ensure_schema()
    
    def _ensure_schema(self) -> None:
        """Create outcome_log table."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS outcome_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                tou_period TEXT NOT NULL,
                import_kwh REAL,
                export_kwh REAL,
                solar_production_kwh REAL,
                battery_discharge_kwh REAL,
                actual_cost REAL,
                baseline_cost REAL,
                savings REAL,
                comfort_violations INTEGER,
                max_temp_deviation REAL,
                rooms_exceeded TEXT,
                manual_overrides INTEGER,
                solar_predicted REAL,
                solar_actual REAL,
                solar_error_pct REAL,
                load_predicted REAL,
                load_actual REAL,
                load_error_pct REAL
            )
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_outcome_period ON outcome_log(period_start)"
        )
        self.db.commit()
    
    async def measure_period_outcome(
        self,
        period_start: datetime,
        period_end: datetime,
        tou_period: str,
        predictions: dict,
    ) -> OutcomeMeasurement:
        """Measure outcomes for a completed TOU period."""
        
        # Get energy data from HA statistics
        import_kwh = await self._get_energy_stat(
            "sensor.enphase_grid_import", period_start, period_end
        )
        export_kwh = await self._get_energy_stat(
            "sensor.enphase_grid_export", period_start, period_end
        )
        solar_kwh = await self._get_energy_stat(
            "sensor.enphase_solar_production", period_start, period_end
        )
        battery_kwh = await self._get_energy_stat(
            "sensor.enphase_battery_discharge", period_start, period_end
        )
        
        # Calculate costs
        rate = self._get_rate_for_period(tou_period)
        actual_cost = import_kwh * rate - export_kwh * rate
        
        # Baseline: import everything consumed
        total_consumption = await self._get_total_consumption(period_start, period_end)
        baseline_cost = total_consumption * rate
        
        savings = baseline_cost - actual_cost
        
        # Comfort outcomes
        violations = await self._count_comfort_violations(period_start, period_end)
        max_dev, rooms = await self._get_max_temp_deviation(period_start, period_end)
        overrides = await self._count_overrides(period_start, period_end)
        
        # Prediction accuracy
        solar_predicted = predictions.get("solar_kwh", 0)
        solar_error = ((solar_kwh - solar_predicted) / solar_predicted * 100) if solar_predicted else 0
        
        load_predicted = predictions.get("load_kwh", 0)
        load_error = ((total_consumption - load_predicted) / load_predicted * 100) if load_predicted else 0
        
        outcome = OutcomeMeasurement(
            period_start=period_start,
            period_end=period_end,
            tou_period=tou_period,
            import_kwh=import_kwh,
            export_kwh=export_kwh,
            solar_production_kwh=solar_kwh,
            battery_discharge_kwh=battery_kwh,
            actual_cost=actual_cost,
            baseline_cost=baseline_cost,
            savings=savings,
            comfort_violations=violations,
            max_temp_deviation=max_dev,
            rooms_exceeded=rooms,
            manual_overrides=overrides,
            solar_predicted=solar_predicted,
            solar_actual=solar_kwh,
            solar_error_pct=solar_error,
            load_predicted=load_predicted,
            load_actual=total_consumption,
            load_error_pct=load_error,
        )
        
        self._store_outcome(outcome)
        return outcome
    
    async def _get_energy_stat(
        self,
        entity_id: str,
        start: datetime,
        end: datetime,
    ) -> float:
        """Get energy consumption/production from HA statistics."""
        # Use recorder statistics API
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period
        
        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            {entity_id},
            "hour",
            None,
            {"sum"},
        )
        
        if entity_id in stats and stats[entity_id]:
            values = [s["sum"] for s in stats[entity_id] if s.get("sum")]
            if values:
                return max(values) - min(values)
        
        return 0.0
    
    def _get_rate_for_period(self, tou_period: str) -> float:
        """Get TOU rate for period."""
        rates = {
            "off_peak": 0.0435,
            "mid_peak": 0.0932,
            "peak": 0.1618,
        }
        return rates.get(tou_period, 0.10)
```

---

## 6. PATTERN ANALYSIS

### Purpose

Analyze **recurring patterns** in overrides and outcomes for insights.

### Override Pattern Detection

```python
@dataclass
class OverridePattern:
    """A detected pattern in user overrides."""
    
    description: str              # Human-readable
    condition: str                # "outdoor_temp > 95"
    frequency: float              # 0.0-1.0
    confidence: float             # Statistical confidence
    sample_size: int
    recommendation: str | None


class PatternAnalyzer:
    """Analyze override and outcome patterns."""
    
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)
    
    def analyze_override_patterns(self, days: int = 30) -> list[OverridePattern]:
        """Find patterns in user overrides."""
        patterns = []
        
        # Get overrides with their decision context
        overrides = self._get_overrides_with_context(days)
        
        if len(overrides) < 10:
            return []  # Not enough data
        
        # Analyze by outdoor temperature
        patterns.extend(self._analyze_by_outdoor_temp(overrides))
        
        # Analyze by time of day
        patterns.extend(self._analyze_by_time(overrides))
        
        # Analyze by room
        patterns.extend(self._analyze_by_room(overrides))
        
        # Analyze by day of week
        patterns.extend(self._analyze_by_day_of_week(overrides))
        
        return sorted(patterns, key=lambda p: -p.frequency)
    
    def _analyze_by_outdoor_temp(self, overrides: list[dict]) -> list[OverridePattern]:
        """Find temperature-correlated override patterns."""
        patterns = []
        
        # Check high temperature correlation
        hot_overrides = [o for o in overrides if o.get("outdoor_temp", 0) > 95]
        if hot_overrides:
            freq = len(hot_overrides) / len(overrides)
            if freq > 0.3:  # Significant
                patterns.append(OverridePattern(
                    description=f"User overrides {freq:.0%} of time when outdoor > 95°F",
                    condition="outdoor_temp > 95",
                    frequency=freq,
                    confidence=self._calculate_confidence(len(hot_overrides), len(overrides)),
                    sample_size=len(hot_overrides),
                    recommendation="Consider reducing coast offset on very hot days",
                ))
        
        return patterns
    
    def _analyze_by_time(self, overrides: list[dict]) -> list[OverridePattern]:
        """Find time-of-day override patterns."""
        patterns = []
        
        evening_overrides = [o for o in overrides if 17 <= o.get("hour", 0) <= 20]
        if evening_overrides:
            freq = len(evening_overrides) / len(overrides)
            if freq > 0.4:
                patterns.append(OverridePattern(
                    description=f"User overrides {freq:.0%} of time during evening (5-8pm)",
                    condition="hour between 17-20",
                    frequency=freq,
                    confidence=self._calculate_confidence(len(evening_overrides), len(overrides)),
                    sample_size=len(evening_overrides),
                    recommendation="Evening comfort may be higher priority than savings",
                ))
        
        return patterns
    
    def analyze_prediction_drift(self, days: int = 30) -> dict:
        """Analyze systematic errors in predictions."""
        outcomes = self._get_outcomes(days)
        
        if len(outcomes) < 10:
            return {}
        
        import statistics
        
        # Solar forecast bias
        solar_errors = [
            (o["solar_actual"] - o["solar_predicted"]) / o["solar_predicted"]
            for o in outcomes
            if o.get("solar_predicted", 0) > 0
        ]
        
        solar_bias = statistics.mean(solar_errors) if solar_errors else 0
        solar_std = statistics.stdev(solar_errors) if len(solar_errors) > 1 else 0.2
        
        # Load forecast bias
        load_errors = [
            (o["load_actual"] - o["load_predicted"]) / o["load_predicted"]
            for o in outcomes
            if o.get("load_predicted", 0) > 0
        ]
        
        load_bias = statistics.mean(load_errors) if load_errors else 0
        load_std = statistics.stdev(load_errors) if len(load_errors) > 1 else 0.2
        
        return {
            "solar_forecast_bias": solar_bias,
            "solar_forecast_std": solar_std,
            "solar_correction_multiplier": 1.0 / (1.0 + solar_bias) if solar_bias != -1 else 1.0,
            "load_forecast_bias": load_bias,
            "load_forecast_std": load_std,
            "load_correction_multiplier": 1.0 / (1.0 + load_bias) if load_bias != -1 else 1.0,
            "sample_size": len(outcomes),
        }
    
    def calculate_optimization_effectiveness(self, days: int = 30) -> dict:
        """Calculate how effective optimization strategies are."""
        outcomes = self._get_outcomes(days)
        
        if not outcomes:
            return {}
        
        total_savings = sum(o.get("savings", 0) for o in outcomes)
        total_baseline = sum(o.get("baseline_cost", 0) for o in outcomes)
        
        peak_outcomes = [o for o in outcomes if o.get("tou_period") == "peak"]
        peak_savings = sum(o.get("savings", 0) for o in peak_outcomes)
        
        return {
            "total_savings": total_savings,
            "savings_per_day": total_savings / days if days else 0,
            "savings_percentage": (total_savings / total_baseline * 100) if total_baseline else 0,
            "peak_savings": peak_savings,
            "peak_export_kwh": sum(o.get("export_kwh", 0) for o in peak_outcomes),
            "comfort_violations_total": sum(o.get("comfort_violations", 0) for o in outcomes),
            "override_rate": sum(o.get("manual_overrides", 0) for o in outcomes) / len(outcomes),
        }
    
    def _calculate_confidence(self, successes: int, total: int) -> float:
        """Calculate statistical confidence using Wilson score interval."""
        if total == 0:
            return 0.0
        
        import math
        
        z = 1.96  # 95% confidence
        p = successes / total
        
        denominator = 1 + z * z / total
        center = p + z * z / (2 * total)
        spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
        
        lower_bound = (center - spread) / denominator
        return max(0.0, lower_bound)
    
    def _get_overrides_with_context(self, days: int) -> list[dict]:
        """Get override records with decision context."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor = self.db.execute("""
            SELECT c.*, d.context_json
            FROM compliance_log c
            JOIN decision_log d ON c.decision_id = d.id
            WHERE c.override_detected = 1
            AND c.timestamp >= ?
        """, (cutoff,))
        
        results = []
        for row in cursor:
            record = dict(zip([d[0] for d in cursor.description], row))
            # Parse context JSON
            context = json.loads(record.get("context_json", "{}"))
            record["outdoor_temp"] = context.get("outdoor_temp_f", 0)
            record["hour"] = datetime.fromisoformat(record["timestamp"]).hour
            record["weekday"] = datetime.fromisoformat(record["timestamp"]).weekday()
            results.append(record)
        
        return results
    
    def _get_outcomes(self, days: int) -> list[dict]:
        """Get outcome records."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor = self.db.execute("""
            SELECT * FROM outcome_log
            WHERE timestamp >= ?
        """, (cutoff,))
        
        return [dict(zip([d[0] for d in cursor.description], row)) for row in cursor]
```

---

## 7. BAYESIAN PARAMETER LEARNING

### Purpose

**Automatically adjust** coordinator parameters based on observed data.

### Implementation

```python
import random
from dataclasses import dataclass

@dataclass
class ParameterBelief:
    """Bayesian belief about a parameter value."""
    mean: float
    std: float
    
    def sample(self) -> float:
        """Sample from the belief distribution."""
        return random.gauss(self.mean, self.std)
    
    def update(self, observation: float, weight: float = 1.0) -> "ParameterBelief":
        """Bayesian update with new observation."""
        prior_precision = 1.0 / (self.std ** 2) if self.std > 0 else 1.0
        obs_precision = weight
        
        total_precision = prior_precision + obs_precision
        new_mean = (self.mean * prior_precision + observation * obs_precision) / total_precision
        new_std = max(0.1, self.std * 0.95)  # Slowly reduce uncertainty
        
        return ParameterBelief(mean=new_mean, std=new_std)


class BayesianParameterLearner:
    """Learn optimal coordinator parameters from observed outcomes."""
    
    def __init__(self, coordinator_id: str, db_path: str):
        self.coordinator_id = coordinator_id
        self.db = sqlite3.connect(db_path)
        self._ensure_schema()
        
        # Initialize prior beliefs
        self.beliefs = {
            "coast_setpoint_offset": ParameterBelief(mean=3.0, std=0.5),
            "pre_cool_setpoint_offset": ParameterBelief(mean=-3.0, std=0.5),
            "pre_cool_window_minutes": ParameterBelief(mean=60, std=15),
            "sleep_max_offset": ParameterBelief(mean=1.5, std=0.3),
            "export_soc_threshold": ParameterBelief(mean=60, std=10),
            "reserve_level": ParameterBelief(mean=20, std=5),
        }
        
        self._load_beliefs()
    
    def _ensure_schema(self) -> None:
        """Create tables for beliefs and history."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS parameter_beliefs (
                coordinator_id TEXT NOT NULL,
                parameter_name TEXT NOT NULL,
                mean REAL NOT NULL,
                std REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (coordinator_id, parameter_name)
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS parameter_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                coordinator_id TEXT NOT NULL,
                parameter_name TEXT NOT NULL,
                old_value REAL,
                new_value REAL NOT NULL,
                reason TEXT
            )
        """)
        self.db.commit()
    
    def update_from_outcomes(self, analysis_days: int = 7) -> dict[str, float]:
        """Update parameter beliefs based on recent outcomes."""
        
        updates = {}
        analyzer = PatternAnalyzer(str(self.db.path))
        
        # Get patterns and drift
        override_patterns = analyzer.analyze_override_patterns(analysis_days)
        drift = analyzer.analyze_prediction_drift(analysis_days)
        effectiveness = analyzer.calculate_optimization_effectiveness(analysis_days)
        
        # Update coast offset based on override patterns
        for pattern in override_patterns:
            if "outdoor" in pattern.condition and pattern.frequency > 0.5:
                current = self.beliefs["coast_setpoint_offset"]
                # High override rate → reduce offset
                optimal = current.mean * (1 - pattern.frequency * 0.3)
                self.beliefs["coast_setpoint_offset"] = current.update(
                    optimal, weight=pattern.confidence
                )
                updates["coast_setpoint_offset"] = self.beliefs["coast_setpoint_offset"].mean
        
        # Update based on comfort violations
        violations_per_day = effectiveness.get("comfort_violations_total", 0) / analysis_days
        if violations_per_day > 1:
            current = self.beliefs["coast_setpoint_offset"]
            self.beliefs["coast_setpoint_offset"] = current.update(
                current.mean * 0.9, weight=0.5  # 10% reduction
            )
            updates["coast_setpoint_offset"] = self.beliefs["coast_setpoint_offset"].mean
        
        # Update battery threshold based on export effectiveness
        if effectiveness.get("peak_export_kwh", 0) < 2:
            current = self.beliefs["export_soc_threshold"]
            self.beliefs["export_soc_threshold"] = current.update(
                current.mean - 5, weight=0.3  # Lower threshold to export more
            )
            updates["export_soc_threshold"] = self.beliefs["export_soc_threshold"].mean
        
        # Save updates
        self._save_beliefs()
        
        for param, new_value in updates.items():
            self._log_parameter_change(param, new_value, "bayesian_update")
        
        return updates
    
    def get_parameters(self) -> dict[str, float]:
        """Get current parameter values for coordinator use."""
        return {name: belief.mean for name, belief in self.beliefs.items()}
    
    def get_parameter_with_exploration(self, name: str) -> float:
        """Get parameter with occasional exploration (for A/B testing)."""
        if name not in self.beliefs:
            raise KeyError(f"Unknown parameter: {name}")
        
        # 10% exploration rate
        if random.random() < 0.1:
            return self.beliefs[name].sample()
        
        return self.beliefs[name].mean
    
    def _save_beliefs(self) -> None:
        """Persist beliefs to database."""
        for name, belief in self.beliefs.items():
            self.db.execute("""
                INSERT OR REPLACE INTO parameter_beliefs
                (coordinator_id, parameter_name, mean, std, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                self.coordinator_id,
                name,
                belief.mean,
                belief.std,
                datetime.now().isoformat(),
            ))
        self.db.commit()
    
    def _load_beliefs(self) -> None:
        """Load beliefs from database."""
        cursor = self.db.execute("""
            SELECT parameter_name, mean, std
            FROM parameter_beliefs
            WHERE coordinator_id = ?
        """, (self.coordinator_id,))
        
        for name, mean, std in cursor:
            if name in self.beliefs:
                self.beliefs[name] = ParameterBelief(mean=mean, std=std)
    
    def _log_parameter_change(
        self, 
        name: str, 
        new_value: float, 
        reason: str
    ) -> None:
        """Log parameter change for audit trail."""
        self.db.execute("""
            INSERT INTO parameter_history
            (timestamp, coordinator_id, parameter_name, new_value, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            self.coordinator_id,
            name,
            new_value,
            reason,
        ))
        self.db.commit()
```

---

## 8. DIAGNOSTIC SENSORS

### Standard Sensors Per Coordinator

Each coordinator should expose these diagnostic sensors:

```yaml
# Situation sensor
sensor.{coordinator}_situation:
  state: "{current_situation}"
  attributes:
    urgency: 0-100
    confidence: 0.0-1.0
    time_horizon_minutes: int
    last_decision_timestamp: ISO datetime

# Compliance sensor
sensor.{coordinator}_compliance:
  state: "full" | "partial" | "overridden"
  attributes:
    compliance_rate_today: 0.0-1.0
    compliance_rate_7day: 0.0-1.0
    override_count_today: int
    override_sources: list[str]
    devices_compliant: list[str]
    devices_overridden: list[str]

# Effectiveness sensor
sensor.{coordinator}_effectiveness:
  state: "excellent" | "good" | "fair" | "poor"
  attributes:
    savings_today: float (currency)
    savings_7day: float
    savings_vs_baseline_pct: float
    comfort_violations_today: int
    prediction_accuracy_7day: 0.0-1.0

# Learning sensor
sensor.{coordinator}_learning:
  state: "active" | "paused" | "insufficient_data"
  attributes:
    parameters_adjusted_this_week: int
    top_pattern: str (description)
    forecast_bias_correction: float
    last_learning_update: ISO datetime
    recommended_changes: list[str]
```

### Example: Energy Coordinator Sensors

```yaml
sensor.energy_coordinator_situation:
  state: "EXPENSIVE"
  attributes:
    urgency: 70
    confidence: 0.85
    time_horizon_minutes: 45
    last_decision_timestamp: "2026-01-24T16:30:00"
    export_opportunity: false

sensor.energy_coordinator_compliance:
  state: "partial"
  attributes:
    compliance_rate_today: 0.78
    compliance_rate_7day: 0.82
    override_count_today: 3
    override_sources: ["hvac_manual", "hvac_manual", "pool_app"]
    devices_compliant: ["battery", "evse_a", "evse_b"]
    devices_overridden: ["hvac_zone_1", "pool"]

sensor.energy_coordinator_effectiveness:
  state: "good"
  attributes:
    savings_today: 2.45
    savings_7day: 15.80
    savings_vs_baseline_pct: 23.5
    peak_import_avoided_kwh: 8.3
    peak_export_kwh: 4.1
    comfort_violations_today: 1

sensor.energy_coordinator_learning:
  state: "active"
  attributes:
    parameters_adjusted_this_week: 3
    top_pattern: "HVAC coast overridden 73% when outdoor > 95°F"
    forecast_bias_correction: 0.88
    last_learning_update: "2026-01-20T03:00:00"
    recommended_changes:
      - "Reduce coast_offset from 3.0 to 2.5"
      - "Lower export_soc_threshold from 60 to 55"
```

---

## 9. DATABASE SCHEMA

### Complete Schema

```sql
-- Decision logging
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,
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
CREATE INDEX IF NOT EXISTS idx_decision_situation ON decision_log(situation_classified);

-- Compliance tracking
CREATE TABLE IF NOT EXISTS compliance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    decision_id INTEGER,
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
CREATE INDEX IF NOT EXISTS idx_compliance_compliant ON compliance_log(compliant);
CREATE INDEX IF NOT EXISTS idx_compliance_timestamp ON compliance_log(timestamp);

-- Outcome measurement
CREATE TABLE IF NOT EXISTS outcome_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    tou_period TEXT NOT NULL,
    import_kwh REAL,
    export_kwh REAL,
    solar_production_kwh REAL,
    battery_discharge_kwh REAL,
    actual_cost REAL,
    baseline_cost REAL,
    savings REAL,
    comfort_violations INTEGER,
    max_temp_deviation REAL,
    rooms_exceeded TEXT,
    manual_overrides INTEGER,
    solar_predicted REAL,
    solar_actual REAL,
    solar_error_pct REAL,
    load_predicted REAL,
    load_actual REAL,
    load_error_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_outcome_period ON outcome_log(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_outcome_tou ON outcome_log(tou_period);

-- Bayesian parameter beliefs
CREATE TABLE IF NOT EXISTS parameter_beliefs (
    coordinator_id TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    mean REAL NOT NULL,
    std REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (coordinator_id, parameter_name)
);

-- Parameter change history
CREATE TABLE IF NOT EXISTS parameter_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    old_value REAL,
    new_value REAL NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_param_history ON parameter_history(coordinator_id, parameter_name);
CREATE INDEX IF NOT EXISTS idx_param_timestamp ON parameter_history(timestamp);
```

---

## 10. IMPLEMENTATION GUIDE

### Adding Diagnostics to a New Coordinator

```python
class MyCoordinator:
    """Example coordinator with full diagnostics integration."""
    
    def __init__(self, hass: HomeAssistant, db_path: str):
        self.hass = hass
        
        # Initialize diagnostics components
        self.decision_logger = DecisionLogger(db_path)
        self.compliance_tracker = ComplianceTracker(hass, db_path)
        self.outcome_measurer = OutcomeMeasurer(hass, db_path)
        self.pattern_analyzer = PatternAnalyzer(db_path)
        self.parameter_learner = BayesianParameterLearner("my_coordinator", db_path)
        
        # Get learned parameters
        self.parameters = self.parameter_learner.get_parameters()
    
    async def async_init(self) -> None:
        """Initialize and schedule learning updates."""
        # Schedule weekly learning update
        async_track_time_interval(
            self.hass,
            self._weekly_learning_update,
            timedelta(days=7),
        )
    
    async def make_decision(self) -> None:
        """Make a decision with full logging."""
        # 1. Gather context
        context = await self._gather_context()
        
        # 2. Make decision (using learned parameters)
        coast_offset = self.parameters.get("coast_setpoint_offset", 3.0)
        action = self._decide(context, coast_offset)
        
        # 3. Log decision
        decision_id = await self.decision_logger.log_decision(DecisionLog(
            timestamp=datetime.now(),
            coordinator_id="my_coordinator",
            decision_type="main_decision",
            situation_classified=action.situation,
            urgency=action.urgency,
            confidence=0.85,
            context=context,
            action=asdict(action),
        ))
        
        # 4. Execute
        await self._execute(action)
        
        # 5. Schedule compliance check
        await self.compliance_tracker.schedule_check(
            decision_id,
            action.device_type,
            action.device_id,
            action.commanded_state,
        )
    
    async def _weekly_learning_update(self, now: datetime) -> None:
        """Run weekly parameter learning."""
        updates = self.parameter_learner.update_from_outcomes(analysis_days=7)
        
        if updates:
            self.parameters = self.parameter_learner.get_parameters()
            _LOGGER.info(f"Updated parameters: {updates}")
```

### Diagnostic Sensor Setup

```python
async def async_setup_entry(hass, entry, async_add_entities):
    """Set up diagnostic sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    sensors = [
        CoordinatorSituationSensor(coordinator),
        CoordinatorComplianceSensor(coordinator),
        CoordinatorEffectivenessSensor(coordinator),
        CoordinatorLearningSensor(coordinator),
    ]
    
    async_add_entities(sensors)


class CoordinatorComplianceSensor(SensorEntity):
    """Compliance diagnostic sensor."""
    
    def __init__(self, coordinator):
        self._coordinator = coordinator
        self._attr_name = f"{coordinator.name} Compliance"
        self._attr_unique_id = f"{coordinator.coordinator_id}_compliance"
    
    @property
    def state(self) -> str:
        """Return compliance state."""
        rate = self._coordinator.compliance_tracker.get_compliance_rate()
        if rate >= 0.9:
            return "full"
        elif rate >= 0.5:
            return "partial"
        return "overridden"
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return compliance details."""
        return {
            "compliance_rate_today": self._coordinator.compliance_tracker.get_compliance_rate(days=1),
            "compliance_rate_7day": self._coordinator.compliance_tracker.get_compliance_rate(days=7),
            # ... more attributes
        }
```

---

## 11. COORDINATOR-SPECIFIC EXTENSIONS

### Energy Coordinator

Additional metrics:
- TOU period breakdown (savings per period)
- Battery efficiency (discharge vs load offset)
- Export value captured
- Solar forecast accuracy by weather condition

### HVAC Coordinator

Additional metrics:
- Per-zone compliance rates
- Pre-cool effectiveness (thermal mass retention)
- Sleep hour violation tracking
- Fan coordination activations

### Pool Coordinator

Additional metrics:
- Runtime vs TOU period alignment
- Chemical dosing timing effectiveness
- Pump efficiency trends

### Lighting Coordinator

Additional metrics:
- Occupancy prediction accuracy
- Scene activation patterns
- Energy saved vs baseline

---

## APPENDIX: QUICK REFERENCE

### Key Tables

| Table | Purpose | Retention |
|-------|---------|-----------|
| `decision_log` | Every coordinator decision | 90 days |
| `compliance_log` | Commanded vs actual state | 90 days |
| `outcome_log` | Period-level measurements | 1 year |
| `parameter_beliefs` | Current learned parameters | Forever |
| `parameter_history` | Parameter change audit trail | 1 year |

### Key Metrics

| Metric | Good | Fair | Poor |
|--------|------|------|------|
| Compliance Rate | > 80% | 50-80% | < 50% |
| Savings vs Baseline | > 20% | 10-20% | < 10% |
| Prediction Accuracy | > 85% | 70-85% | < 70% |
| Comfort Violations/Day | < 1 | 1-3 | > 3 |

### Learning Schedule

| Analysis | Frequency | Actions |
|----------|-----------|---------|
| Compliance check | 2 min after action | Log override |
| Outcome measurement | Per TOU period | Update metrics |
| Pattern analysis | Weekly | Surface insights |
| Parameter update | Weekly | Adjust beliefs |

---

**Document Status:** Design Complete  
**Applies To:** All URA Domain Coordinators  
**Database:** Shared SQLite with coordinator-specific tables
