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
from homeassistant.util import dt as dt_util

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
            async with database._db() as db:
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
            async with database._db() as db:
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
            async with database._db() as db:
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

        # v4.6.3 D6/D11/D12: emit anomaly only on compliance violation (not
        # every decision — that would flood the table per the plan).
        if not compliant and record.override_detected:
            await self._emit_compliance_violation_anomaly(record)

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

    async def _emit_compliance_violation_anomaly(self, record: "ComplianceRecord") -> None:
        """Emit AnomalyEvent for compliance violations (D6 / D11 / D12).

        Called only when `not compliant and override_detected` — NOT for
        every decision, so the table is not flooded.  Never raises.
        """
        try:
            from .anomaly_event import (  # noqa: PLC0415
                AnomalyEvent,
                AnomalySeverity,
                AnomalyType,
                build_context_json,
            )
            _ctx = build_context_json(
                zone_id=record.scope if record.scope.startswith("zone:") else None,
                room_id=record.scope if record.scope.startswith("room:") else None,
                source_signal="compliance_check",
                extra={
                    "decision_id": record.decision_id,
                    "scope": record.scope,
                    "device_type": record.device_type,
                    "device_id": record.device_id,
                    "override_source": record.override_source,
                    "override_duration_minutes": record.override_duration_minutes,
                    "deviation": record.deviation_details,
                },
            )
            _event = AnomalyEvent(
                coordinator="compliance",
                type="compliance.override_detected",
                severity=AnomalySeverity.WARNING,
                anomaly_type=AnomalyType.POINT_IN_TIME,
                detected_at=record.timestamp.isoformat(),
                payload=_ctx,
                entity_id=record.device_id,
            )
            database = self._database
            if database is not None:
                await database.save_anomaly_event(_event)
                _LOGGER.info(
                    "Compliance violation anomaly emitted: scope=%s device=%s",
                    record.scope, record.device_id,
                )
            # D12: fire activity_logger (awaited — A5 fix: avoid untracked task)
            # A2 fix: include device_id + timestamp in description to avoid dedup
            # masking distinct violations of the same device within the 60s window.
            activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if activity_logger:
                await activity_logger.log(
                    coordinator="compliance",
                    action="anomaly",
                    description=(
                        f"Compliance violation: {record.device_type} {record.device_id} "
                        f"overridden at {record.scope} t={record.timestamp.isoformat()[:19]}"
                    ),
                    importance="notable",
                    entity_id=record.device_id,
                    details={
                        "type": "compliance.override_detected",
                        "scope": record.scope,
                        "override_source": record.override_source,
                    },
                )
        except Exception:
            _LOGGER.debug("_emit_compliance_violation_anomaly failed (swallowed)", exc_info=True)

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
            async with database._db() as db:
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
            async with database._db() as db:
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
            async with database._db() as db:
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
        sensitivity_multiplier: float = 1.0,
        suppressed_metric_names: Optional["frozenset[str]"] = None,
    ) -> None:
        """Initialize the anomaly detector.

        Args:
            sensitivity_multiplier: Multiplies the default z-score thresholds.
                > 1.0 = quieter (fewer flags); < 1.0 = more sensitive (more flags).
                Applied once at init from the user's options-flow sensitivity bucket.
                See ANOMALY_SENSITIVITY_MULTIPLIERS in const.py.
            suppressed_metric_names: v4.6.5.3 surface fix. Metrics in this set
                are treated as "in-memory only" — `record_observation` still runs
                so `_active_anomalies` grows for diagnostic visibility, but
                `get_worst_severity()` and the `active_anomalies` count in
                `get_status_summary()` EXCLUDE them. Without this filter, the
                per-coordinator anomaly sensor reports `state: critical` whenever
                a degenerate-shape metric (e.g. v4.6.5-suppressed
                `hvac.zone_call_frequency`) fires its in-memory anomaly — which
                is misleading because the metric was explicitly suppressed from
                persistence precisely because its shape is degenerate.
                Companion to each coordinator's module-level
                `*_SUPPRESSED_FROM_PERSISTENCE` constant from v4.6.5.1 P2.
        """
        self.hass = hass
        self.coordinator_id = coordinator_id
        self.metric_names = metric_names
        self.minimum_samples = minimum_samples or self.MINIMUM_SAMPLES
        # v4.6.3 D10: Apply sensitivity multiplier to z-thresholds at init time.
        # Reload the coordinator entry to change sensitivity (no live tuning).
        m = max(0.1, float(sensitivity_multiplier))  # guard against zero/negative
        self.Z_SCORE_ADVISORY = self.__class__.Z_SCORE_ADVISORY * m
        self.Z_SCORE_ALERT = self.__class__.Z_SCORE_ALERT * m
        self.Z_SCORE_CRITICAL = self.__class__.Z_SCORE_CRITICAL * m
        self._sensitivity_multiplier = m
        self._baselines: Dict[tuple, MetricBaseline] = {}
        self._active_anomalies: list[AnomalyRecord] = []
        self._anomalies_today: int = 0
        self._anomaly_reset_date: str = ""
        # v4.6.5.3 surface fix: suppressed metrics filtered out of severity.
        self._suppressed_metric_names: "frozenset[str]" = (
            suppressed_metric_names if suppressed_metric_names is not None
            else frozenset()
        )

    def _persisted_active_anomalies(self) -> list:
        """v4.6.5.3 surface fix: return only the anomalies whose metric is NOT
        in `_suppressed_metric_names`. Used by `get_worst_severity()` and the
        `active_anomalies` count in `get_status_summary()` so the per-
        coordinator anomaly sensor's reported severity matches the
        anomaly_log-eligible signal — not the in-memory count of degenerate-
        shape suppressed metrics.
        """
        if not self._suppressed_metric_names:
            return list(self._active_anomalies)
        return [
            a for a in self._active_anomalies
            if a.metric_name not in self._suppressed_metric_names
        ]

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
        today = dt_util.utcnow().date().isoformat()
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
                    timestamp=dt_util.utcnow(),
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
        """Return the learning status for a given scope.

        v4.5.13: ACTIVE when at least floor(n/2) metrics have a complete
        baseline (sample_count >= minimum_samples), with a floor of 1. For
        4-metric detectors this is a true majority (2 of 4); for 2- and
        3-metric detectors it degenerates to "any one metric complete" —
        which is the deliberate choice for small metric counts where
        requiring multiple complete baselines would leave the detector
        stuck. The aggregate label is a hint; per-metric anomaly raising
        in record_observation:696 still gates on each baseline's own
        sample_count, so dead metrics never produce false anomalies.

        Why the relaxation: previously required ALL metrics, which left
        coordinators (HVAC, presence, safety, security, NM) stuck in
        LEARNING for weeks because some metrics were never being
        recorded — either the record_observation call sites for those
        metrics weren't wired, or the underlying events never fire on
        this install. Dead metrics still show active=False in the
        per-metric details (get_status_summary), so the gap remains
        visible to operators.
        """
        active_metrics = 0
        learning_metrics = 0
        for metric_name in self.metric_names:
            baseline = self._get_baseline(metric_name, scope)
            if baseline.sample_count >= self.minimum_samples:
                active_metrics += 1
            elif baseline.sample_count > 0:
                learning_metrics += 1

        threshold = max(1, len(self.metric_names) // 2)
        if active_metrics >= threshold:
            return LearningStatus.ACTIVE
        elif active_metrics > 0 or learning_metrics > 0:
            return LearningStatus.LEARNING
        return LearningStatus.INSUFFICIENT_DATA

    def get_worst_severity(self) -> AnomalySeverity:
        """Return the worst active anomaly severity.

        v4.6.5.3 surface fix: filters out anomalies for metrics in
        `_suppressed_metric_names` so the per-coordinator anomaly sensor's
        reported severity reflects the anomaly_log-eligible signal, not the
        in-memory firing of suppressed-from-persistence degenerate-shape
        metrics. Without this, the sensor reports `critical` permanently
        whenever a suppressed metric fires (e.g. zone_call_frequency on
        every morning HVAC warm-up).
        """
        persisted = self._persisted_active_anomalies()
        if not persisted:
            return AnomalySeverity.NOMINAL

        severity_order = {
            AnomalySeverity.NOMINAL: 0,
            AnomalySeverity.ADVISORY: 1,
            AnomalySeverity.ALERT: 2,
            AnomalySeverity.CRITICAL: 3,
        }
        worst = max(
            persisted,
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
        """Return a summary of anomaly detection status for diagnostics.

        v4.5.14: top-level `metrics_active_ratio` (e.g. "2/4") and
        `metrics_silent` (list of metric names with 0 samples) make the
        dead-metric reality visible at a glance. The gate relaxation in
        v4.5.13 lets the detector report `active` when only some metrics
        have baselines; without these summary fields, a consumer
        couldn't tell which metrics were silently dead.
        """
        self._maybe_reset_daily_counter()
        active_count = 0
        silent_metrics: list[str] = []
        for metric_name in self.metric_names:
            baseline = self._get_baseline(metric_name, scope)
            if baseline.sample_count >= self.minimum_samples:
                active_count += 1
            elif baseline.sample_count == 0:
                silent_metrics.append(metric_name)
        total = len(self.metric_names) or 1  # avoid "0/0" if empty
        # v4.6.5.3 surface fix: `active_anomalies` reports persisted-eligible
        # count (suppressed metrics excluded). Add `suppressed_active_anomalies`
        # for in-memory-only visibility — operators can still see the suppressed
        # metric is firing without the sensor's primary state going `critical`.
        persisted_active = self._persisted_active_anomalies()
        suppressed_active = (
            len(self._active_anomalies) - len(persisted_active)
        )
        summary: Dict[str, Any] = {
            "coordinator_id": self.coordinator_id,
            "scope": scope,
            "learning_status": self.get_learning_status(scope),
            "minimum_samples": self.minimum_samples,
            "metrics_active_ratio": f"{active_count}/{total}",
            "metrics_silent": silent_metrics,
            "active_anomalies": len(persisted_active),
            "suppressed_active_anomalies": suppressed_active,
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

    async def store_event(self, event: "AnomalyEvent") -> Optional[int]:
        """Canonical writer for AnomalyEvent — delegates to the single
        database DAO so callers without an AnomalyDetector ref can use
        the same write path (v4.6.1 D0 / review fix B2).
        """
        database = self._database
        if database is None:
            return None
        row_id = await database.save_anomaly_event(event)
        if row_id is not None:
            _LOGGER.info(
                "Stored AnomalyEvent: coordinator=%s type=%s severity=%s anomaly_type=%s",
                event.coordinator, event.type, event.severity.name, event.anomaly_type,
            )
        return row_id

    # v4.6.3 D7: store_anomaly() wrapper removed — all call sites migrated to
    # store_event(AnomalyEvent(...)) with canonical payload shape.
    # grep "store_anomaly" should return 0 hits in production code.

    async def get_anomaly_count(self, days: int = 1) -> int:
        """Get count of anomalies in recent period."""
        database = self._database
        if database is None:
            return 0

        # Review A L1: dt_util.utcnow() (tz-aware) — completes the v4.6.11 D2
        # sweep started at lines 798/824 for the AnomalyDetector class.
        # datetime.utcnow() is deprecated in Python 3.12+ and returns a naive
        # datetime (bug class #21). Remaining call sites in ComplianceTracker
        # and DecisionLogger are out of v4.6.11 scope.
        cutoff = (dt_util.utcnow() - timedelta(days=days)).isoformat()

        try:
            async with database._db() as db:
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
        """Load baseline statistics from the database.

        v4.6.5 (M2 fold-in from v4.6.4 review): filter loaded rows against the
        coordinator's current `metric_names` registry. Rows for metrics that
        have been removed (e.g. v4.6.4 P2 deleted `hazard_trigger_frequency`)
        are skipped on load AND deleted from the table to keep DB hygiene.
        Without this filter, orphaned baselines accumulate forever, are
        unreferenced by anything (since the metric isn't in metric_names), and
        cosmetically pollute the table.
        """
        database = self._database
        if database is None:
            return

        valid_metrics = set(self.metric_names)
        orphan_keys: list[tuple[str, str]] = []
        try:
            async with database._db() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT metric_name, scope, mean, variance,
                           sample_count, last_updated
                    FROM metric_baselines
                    WHERE coordinator_id = ?
                """, (self.coordinator_id,))
                rows = await cursor.fetchall()

                loaded = 0
                for row in rows:
                    metric_name = row["metric_name"]
                    scope = row["scope"]
                    if metric_name not in valid_metrics:
                        orphan_keys.append((metric_name, scope))
                        continue
                    key = (metric_name, scope)
                    self._baselines[key] = MetricBaseline(
                        metric_name=metric_name,
                        coordinator_id=self.coordinator_id,
                        scope=scope,
                        mean=row["mean"],
                        variance=row["variance"],
                        sample_count=row["sample_count"],
                        last_updated=row["last_updated"],
                    )
                    loaded += 1

                if orphan_keys:
                    _LOGGER.info(
                        "Pruning %d orphaned baseline row(s) for %s: %s",
                        len(orphan_keys),
                        self.coordinator_id,
                        [f"{m}@{s}" for m, s in orphan_keys],
                    )
                    # v4.6.5 review A-H1: batch the prune into a single DELETE
                    # so we hold the write queue for one statement, not N.
                    # The prune only runs when orphans exist (first restart
                    # after a metric is removed), so this is a one-time cost
                    # rather than ongoing — but keeping the writer slot tight
                    # avoids contention with concurrent setup_entry on the
                    # other AnomalyDetector coordinators.
                    distinct_metrics = {m for m, _ in orphan_keys}
                    placeholders = ",".join("?" for _ in distinct_metrics)
                    await db.execute(
                        f"DELETE FROM metric_baselines "
                        f"WHERE coordinator_id = ? AND metric_name IN ({placeholders})",
                        (self.coordinator_id, *distinct_metrics),
                    )
                    await db.commit()

                _LOGGER.debug(
                    "Loaded %d baselines for %s (skipped %d orphan)",
                    loaded, self.coordinator_id, len(orphan_keys),
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
            async with database._db() as db:
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
            async with database._db() as db:
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
