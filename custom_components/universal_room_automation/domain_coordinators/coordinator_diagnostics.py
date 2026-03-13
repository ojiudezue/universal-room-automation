"""Coordinator diagnostics framework for domain coordinators.

Provides DecisionLogger, ComplianceTracker, AnomalyDetector, and supporting
data structures for all coordinators to log decisions, track compliance,
detect anomalies, and measure outcomes.

v3.6.0-c0.4: Initial implementation from COORDINATOR_DIAGNOSTICS_FRAMEWORK_v2.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

import aiosqlite

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class AnomalySeverity(StrEnum):
    """Severity levels for anomalies."""

    NOMINAL = "nominal"
    ADVISORY = "advisory"  # z-score 2.0-3.0
    ALERT = "alert"  # z-score 3.0-4.0
    CRITICAL = "critical"  # z-score > 4.0


class LearningStatus(StrEnum):
    """Learning status for anomaly detection."""

    INSUFFICIENT_DATA = "insufficient_data"
    LEARNING = "learning"
    ACTIVE = "active"
    PAUSED = "paused"


class ComplianceState(StrEnum):
    """Compliance state values."""

    FULL = "full"
    PARTIAL = "partial"
    OVERRIDDEN = "overridden"


# ============================================================================
# Data classes
# ============================================================================


@dataclass
class DecisionLog:
    """Record of a coordinator decision."""

    timestamp: datetime
    coordinator_id: str
    decision_type: str
    scope: str  # "house", "zone:{name}", "room:{name}"
    situation_classified: str
    urgency: int  # 0-100
    confidence: float  # 0.0-1.0
    context: dict[str, Any] = field(default_factory=dict)
    action: dict[str, Any] = field(default_factory=dict)
    expected_savings_kwh: Optional[float] = None
    expected_cost_savings: Optional[float] = None
    expected_comfort_impact: Optional[int] = None
    constraints_published: List[str] = field(default_factory=list)
    devices_commanded: List[str] = field(default_factory=list)


@dataclass
class ComplianceRecord:
    """Track actual vs commanded state."""

    timestamp: datetime
    decision_id: int
    scope: str
    device_type: str
    device_id: str
    commanded_state: dict[str, Any] = field(default_factory=dict)
    actual_state: dict[str, Any] = field(default_factory=dict)
    compliant: bool = True
    deviation_details: Optional[dict] = None
    override_detected: bool = False
    override_source: Optional[str] = None
    override_duration_minutes: Optional[int] = None


@dataclass
class AnomalyRecord:
    """Record of a detected anomaly."""

    timestamp: datetime
    coordinator_id: str
    scope: str
    metric_name: str
    observed_value: float
    expected_mean: float
    expected_std: float
    z_score: float
    severity: AnomalySeverity
    sample_size: int
    house_state: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolution_notes: Optional[str] = None


@dataclass
class MetricBaseline:
    """Running statistics for a single metric using Welford's online algorithm.

    v3.13.3: Optional max_samples cap for recency weighting. When sample_count
    exceeds max_samples, the effective weight of new samples increases (older
    data fades) by capping the denominator in Welford's update.
    """

    metric_name: str
    coordinator_id: str
    scope: str
    mean: float = 0.0
    variance: float = 1.0
    sample_count: int = 0
    last_updated: Optional[str] = None
    max_samples: int = 0  # 0 = unlimited (classic Welford's)

    # Minimum variance floor to prevent division-by-near-zero in z-scores
    _MIN_VARIANCE: float = field(default=0.01, init=False, repr=False)

    @property
    def std(self) -> float:
        """Standard deviation with minimum floor."""
        effective_variance = max(self.variance, self._MIN_VARIANCE)
        return math.sqrt(effective_variance)

    def update(self, value: float) -> None:
        """Update running statistics with Welford's online algorithm.

        When max_samples > 0, caps the effective sample count so newer
        observations carry more weight than ancient ones (sliding-window
        approximation without storing the full window).
        """
        self.sample_count += 1
        # Use effective_n for Welford's math — caps influence of old data
        effective_n = self.sample_count
        if self.max_samples > 0 and effective_n > self.max_samples:
            effective_n = self.max_samples
        delta = value - self.mean
        self.mean += delta / effective_n
        delta2 = value - self.mean
        self.variance = max(0.0, (
            (self.variance * (effective_n - 1) + delta * delta2)
            / effective_n
        )) if effective_n > 1 else 0.0
        self.last_updated = datetime.utcnow().isoformat()

    def z_score(self, value: float) -> float:
        """Compute z-score for a given value."""
        if self.std < 0.001:
            return 0.0
        return abs(value - self.mean) / self.std


@dataclass
class OutcomeMeasurement:
    """Base class for coordinator outcome measurements."""

    timestamp: datetime
    coordinator_id: str
    period_start: datetime
    period_end: datetime
    scope: str
    decisions_in_period: int = 0
    compliance_rate: float = 1.0
    override_count: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# DecisionLogger
# ============================================================================


class DecisionLogger:
    """Log decisions through the existing URA database."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @property
    def _database(self) -> Any:
        """Get the shared URA database instance."""
        return self.hass.data.get(DOMAIN, {}).get("database")

    async def log_decision(self, decision: DecisionLog) -> Optional[int]:
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

                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)

                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error retrieving decisions: %s", e)
            return []

    async def get_decisions_count(
        self,
        coordinator_id: Optional[str] = None,
        days: int = 1,
    ) -> int:
        """Get count of decisions in recent period."""
        database = self._database
        if database is None:
            return 0

        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        try:
            async with aiosqlite.connect(database.db_file) as db:
                query = "SELECT COUNT(*) FROM decision_log WHERE timestamp >= ?"
                params: list = [cutoff]

                if coordinator_id:
                    query += " AND coordinator_id = ?"
                    params.append(coordinator_id)

                cursor = await db.execute(query, params)
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            _LOGGER.error("Error counting decisions: %s", e)
            return 0


# ============================================================================
# ComplianceTracker
# ============================================================================


class ComplianceTracker:
    """Track compliance with coordinator commands."""

    COMPLIANCE_CHECK_DELAY = 120  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @property
    def _database(self) -> Any:
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
                scope=record.scope,
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
                    query += " AND c.scope = ?"
                    params.append(scope)

                cursor = await db.execute(query, params)
                row = await cursor.fetchone()

                if row and row[0] > 0:
                    return row[1] / row[0]
                return 1.0
        except Exception as e:
            _LOGGER.error("Error getting compliance rate: %s", e)
            return 1.0

    async def get_override_count(
        self,
        coordinator_id: Optional[str] = None,
        days: int = 1,
    ) -> int:
        """Get count of overrides in recent period."""
        database = self._database
        if database is None:
            return 0

        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        try:
            async with aiosqlite.connect(database.db_file) as db:
                query = """
                    SELECT COUNT(*) FROM compliance_log c
                    JOIN decision_log d ON c.decision_id = d.id
                    WHERE c.override_detected = 1 AND c.timestamp >= ?
                """
                params: list = [cutoff]

                if coordinator_id:
                    query += " AND d.coordinator_id = ?"
                    params.append(coordinator_id)

                cursor = await db.execute(query, params)
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            _LOGGER.error("Error counting overrides: %s", e)
            return 0

    async def get_override_sources(
        self,
        coordinator_id: Optional[str] = None,
        days: int = 1,
    ) -> list[str]:
        """Get distinct override sources in recent period."""
        database = self._database
        if database is None:
            return []

        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        try:
            async with aiosqlite.connect(database.db_file) as db:
                query = """
                    SELECT DISTINCT c.override_source FROM compliance_log c
                    JOIN decision_log d ON c.decision_id = d.id
                    WHERE c.override_detected = 1
                    AND c.override_source IS NOT NULL
                    AND c.timestamp >= ?
                """
                params: list = [cutoff]

                if coordinator_id:
                    query += " AND d.coordinator_id = ?"
                    params.append(coordinator_id)

                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()
                return [row[0] for row in rows if row[0]]
        except Exception as e:
            _LOGGER.error("Error getting override sources: %s", e)
            return []


# ============================================================================
# AnomalyDetector
# ============================================================================


class AnomalyDetector:
    """Base anomaly detector using statistical methods.

    Each coordinator instantiates this with its own metric definitions
    and minimum sample sizes.
    """

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
        self._baselines: Dict[tuple, MetricBaseline] = {}
        self._active_anomalies: list[AnomalyRecord] = []
        self._anomalies_today: int = 0
        self._anomaly_reset_date: str = ""

    @property
    def _database(self) -> Any:
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

    def _maybe_reset_daily_counter(self) -> None:
        """Reset daily anomaly counter if date changed."""
        today = datetime.utcnow().date().isoformat()
        if today != self._anomaly_reset_date:
            self._anomalies_today = 0
            self._anomaly_reset_date = today

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

        # Check for anomaly BEFORE updating baseline
        anomaly = None
        if baseline.sample_count >= self.minimum_samples:
            z = baseline.z_score(value)
            severity = self._classify_severity(z)
            if severity != AnomalySeverity.NOMINAL:
                self._maybe_reset_daily_counter()
                self._anomalies_today += 1
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
                )
                self._active_anomalies.append(anomaly)
                # Keep only recent active anomalies (last 50)
                if len(self._active_anomalies) > 50:
                    self._active_anomalies = self._active_anomalies[-50:]

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
        """Return the learning status for a given scope."""
        active_metrics = 0
        learning_metrics = 0
        for metric_name in self.metric_names:
            baseline = self._get_baseline(metric_name, scope)
            if baseline.sample_count >= self.minimum_samples:
                active_metrics += 1
            elif baseline.sample_count > 0:
                learning_metrics += 1

        if active_metrics == len(self.metric_names):
            return LearningStatus.ACTIVE
        elif active_metrics > 0 or learning_metrics > 0:
            return LearningStatus.LEARNING
        return LearningStatus.INSUFFICIENT_DATA

    def get_worst_severity(self) -> AnomalySeverity:
        """Return the worst active anomaly severity."""
        if not self._active_anomalies:
            return AnomalySeverity.NOMINAL

        severity_order = {
            AnomalySeverity.NOMINAL: 0,
            AnomalySeverity.ADVISORY: 1,
            AnomalySeverity.ALERT: 2,
            AnomalySeverity.CRITICAL: 3,
        }
        worst = max(
            self._active_anomalies,
            key=lambda a: severity_order.get(a.severity, 0),
        )
        return worst.severity

    def get_worst_metric(self) -> tuple[str, float]:
        """Return the metric name and z-score of the worst active anomaly."""
        if not self._active_anomalies:
            return ("", 0.0)
        worst = max(self._active_anomalies, key=lambda a: a.z_score)
        return (worst.metric_name, worst.z_score)

    def get_status_summary(self, scope: str = "house") -> dict:
        """Return a summary of anomaly detection status for diagnostics."""
        self._maybe_reset_daily_counter()
        summary: Dict[str, Any] = {
            "coordinator_id": self.coordinator_id,
            "scope": scope,
            "learning_status": self.get_learning_status(scope),
            "minimum_samples": self.minimum_samples,
            "active_anomalies": len(self._active_anomalies),
            "anomalies_today": self._anomalies_today,
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

    async def get_anomaly_count(self, days: int = 1) -> int:
        """Get count of anomalies in recent period."""
        database = self._database
        if database is None:
            return 0

        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        try:
            async with aiosqlite.connect(database.db_file) as db:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM anomaly_log "
                    "WHERE coordinator_id = ? AND timestamp >= ?",
                    (self.coordinator_id, cutoff),
                )
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            _LOGGER.error("Error counting anomalies: %s", e)
            return 0

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
                _LOGGER.debug(
                    "Loaded %d baselines for %s",
                    len(rows), self.coordinator_id,
                )
        except Exception as e:
            _LOGGER.debug(
                "Error loading baselines for %s (may not exist yet): %s",
                self.coordinator_id, e,
            )

    async def save_baselines(self) -> None:
        """Persist baseline statistics to the database."""
        database = self._database
        if database is None:
            return

        try:
            async with aiosqlite.connect(database.db_file) as db:
                for _key, baseline in self._baselines.items():
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
                _LOGGER.debug(
                    "Saved %d baselines for %s",
                    len(self._baselines), self.coordinator_id,
                )
        except Exception as e:
            _LOGGER.error("Error saving baselines: %s", e)

    def clear_active_anomalies(self) -> None:
        """Clear active anomalies (e.g., after resolution)."""
        self._active_anomalies.clear()


# ============================================================================
# OutcomeMeasurer
# ============================================================================


class OutcomeMeasurer:
    """Measure and record outcomes for any coordinator type."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @property
    def _database(self) -> Any:
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
                    json.dumps(outcome.metrics),
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Error storing outcome: %s", e)
            return None
