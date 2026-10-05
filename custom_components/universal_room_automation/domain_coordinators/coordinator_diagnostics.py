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
from datetime import datetime, timedelta, timezone
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


def _w1c_preset_of(hass: Any, state: Any, default: Any, entity_id: Any = None) -> Any:
    """W1-C P2 R16: the thermostat profile's projection of ``preset_mode``
    (Carrier / Generic: the raw attribute verbatim)."""
    from .hvac_strategy import preset_of_for  # noqa: PLC0415
    return preset_of_for(hass, entity_id or getattr(state, "entity_id", None), state, default)


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
# Anomaly coverage vocabulary (HVAC-ANOMALY-BLIND-1 residual A)
# ============================================================================
#
# `partial` is a SENSOR STATE meaning "some declared metric cannot see" — it is
# deliberately NOT an AnomalySeverity member (Bug Class #22): it must stay out
# of `_SEVERITY_RANK`, `map_diag_severity` and every severity roll-up.
COVERAGE_PARTIAL = "partial"
COVERAGE_FULL = "full"

# Per-metric coverage reasons (first match wins, in this order; see
# AnomalyDetector.get_coverage). `stale` is reserved for the parked D5.
COVERAGE_REASON_STALE = "stale"
COVERAGE_REASON_OK = "ok"
COVERAGE_REASON_LEARNING = "learning"
COVERAGE_REASON_NOT_COLLECTING = "not_collecting"
COVERAGE_REASON_NOT_WIRED = "not_wired"
COVERAGE_REASON_NEVER_FED = "never_fed"

# A metric is blind when it has no mature data. Suppressed (muted) and
# constant-baseline (hair-triggered) metrics are annotations, never blind.
BLIND_COVERAGE_REASONS: "frozenset[str]" = frozenset({
    COVERAGE_REASON_LEARNING,
    COVERAGE_REASON_NOT_COLLECTING,
    COVERAGE_REASON_NEVER_FED,
    COVERAGE_REASON_NOT_WIRED,
    COVERAGE_REASON_STALE,
})

# Operator ruling 2026-09-29 ("we shouldn't use learning if it has learned or
# there is enough data samples"): `learning` means ACTIVELY COLLECTING. A
# below-gate metric whose newest sample (max `last_updated` across its scopes)
# is older than this many days is `not_collecting` — blind, so the sensor
# reads `partial`, never `learning` forever (e.g. safety.active_hazard_count,
# 42/720, last sample 2026-09-04, fed only when a hazard fires).
# Rung 1 (module constant): a protocol window whose change should be reviewed.
# A metric with data but no parseable timestamp is NOT judged stalled.
ANOMALY_LEARNING_STALL_DAYS: int = 7


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
        # A-M2 LOW: timezone-aware UTC (naive utcnow deprecated in 3.12+
        # and confuses downstream ISO parsers that expect an offset).
        self.last_updated = datetime.now(timezone.utc).isoformat()

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
        # v4.7.15 D6: Compliance defer gate.
        # When ON, suppress compliance-violation anomalies if signal_consensus
        # has been below 0.6 for >= 60 s sustained. Operator can disable via
        # switch.ura_coordinator_manager_compliance_consensus_defer_gate
        # ("Compliance Presence Wait") for rollback without restart. Default ON.
        self._compliance_defer_gate_enabled: bool = True
        # UNLOAD-SYMMETRY-TASK-HYGIENE-1: retained one-shot ``async_call_later``
        # unsubs from ``schedule_check`` so an entry unload can cancel any
        # pending compliance verifications before they fire against a
        # torn-down coordinator.
        self._pending_check_unsubs: list = []

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
        """Schedule a compliance check after command execution.

        UNLOAD-SYMMETRY-TASK-HYGIENE-1 fix-up (2026-09-16): ``schedule_check``
        is a PER-GOVERNED-COMMAND hot path and the CM's shared
        ``ComplianceTracker`` lives for the process lifetime. If the retained
        one-shot unsub stayed on ``_pending_check_unsubs`` after its
        ``async_call_later`` fired, the list would grow monotonically (each
        entry still pins ``hass`` + ``HassJob`` + closure). The self-removing
        idiom (mirrors ``hvac.py:1351 _unsub_kick``) removes the entry from
        the retention list at fire time so only genuinely-pending unsubs
        remain — bounded retention, still cancellable on teardown.
        """
        _captured_unsub = None

        async def _delayed_check(_now: Any = None) -> None:
            # Self-removal on fire: drop the retention entry BEFORE doing
            # the work so a concurrent ``async_teardown`` can't try to
            # cancel an already-fired unsub.
            if _captured_unsub is not None:
                try:
                    self._pending_check_unsubs.remove(_captured_unsub)
                except ValueError:
                    pass  # Already removed by teardown — benign
            await self._check_compliance(
                decision_id, scope, device_type, device_id, commanded_state
            )

        _captured_unsub = async_call_later(
            self.hass,
            self.COMPLIANCE_CHECK_DELAY,
            _delayed_check,
        )
        self._pending_check_unsubs.append(_captured_unsub)

    def async_teardown(self) -> None:
        """Cancel any pending scheduled compliance checks.

        UNLOAD-SYMMETRY-TASK-HYGIENE-1: called from HVACCoordinator
        ``async_teardown`` and CoordinatorManager ``async_stop`` so
        deferred ``_delayed_check`` callbacks cannot fire against a
        torn-down coordinator after an entry unload/reload.

        DELIBERATE DROP (2026-09-16 fix-up, Review B): cancelling a
        pending ``_delayed_check`` means the compliance-verification row
        for THAT governed command is never written — the tracker resolves
        state live (no queue, no persisted intent). This is the correct
        trade-off: firing against a torn-down coordinator would read
        undefined state and be worse than a missed audit row.
        A reload inside the ``COMPLIANCE_CHECK_DELAY`` (120s) window
        therefore drops at most one row per active governed command.
        No backstop needed; documented as intentional in the release
        README so post-hoc audits don't see it as unexplained data loss.
        """
        for _unsub in list(self._pending_check_unsubs):
            try:
                _unsub()
            except Exception:  # noqa: BLE001 — defensive; unsub may already have fired
                pass
        self._pending_check_unsubs.clear()

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
                # W1-C P2 R16: the thermostat profile's projection.
                "preset_mode": _w1c_preset_of(self.hass, state, None),
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
            if state:
                # W1-C P1: the zone's thermostat profile decides what the
                # anonymous manual hold is (Carrier: preset == "manual").
                from .hvac_strategy import is_manual_hold_for  # noqa: PLC0415

                if is_manual_hold_for(
                    self.hass, device_id, _w1c_preset_of(self.hass, state, None, device_id),
                ):
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

        v4.7.15 D6: Defer gate. When signal_consensus has been below 0.6 for
        >= 60 s sustained, suppress the emit — the disagreement is the more
        likely cause of the apparent override than a true user override.
        Operator can disable via
        switch.ura_coordinator_manager_compliance_consensus_defer_gate.
        """
        # v4.7.15 D6: Consult signal_consensus before emit.
        try:
            if self._compliance_defer_gate_enabled:
                manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                presence = manager.coordinators.get("presence") if (
                    manager is not None and hasattr(manager, "coordinators")
                ) else None
                if presence is not None:
                    consensus = getattr(presence, "_signal_consensus", 1.0)
                    consensus_low_since = getattr(presence, "_consensus_low_since", None)
                    if consensus < 0.6 and consensus_low_since is not None:
                        secs_low = (
                            dt_util.utcnow() - consensus_low_since
                        ).total_seconds()
                        if secs_low >= 60:
                            _LOGGER.info(
                                "v4.7.15 D6: Compliance violation suppressed — "
                                "consensus=%.2f sustained for %.0fs",
                                consensus, secs_low,
                            )
                            return  # Do not emit.
        except Exception:  # noqa: BLE001 — defensive: defer gate must never raise
            _LOGGER.debug(
                "v4.7.15 D6 compliance defer gate failed (swallowed)",
                exc_info=True,
            )

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
# DailyCounter — day-scoped integer counter with declared restart-safety
# ============================================================================
#
# RESTART-SAFETY-DOCTRINE-1 (tranche 1) primitive.
#
# Collapses the identical `self._*_today: int = 0` + `_maybe_reset_daily_counter`
# pattern found across coordinator_diagnostics (F3), security (F11),
# manager (F13), hvac (F14) — six hand-rolled rollover routines audited at
# `docs/planning/AUDIT_restart_safety_classification.md`.
#
# The primitive FORCES the doctrine at declaration:
#   - `persist=False` REQUIRES a `reason` string. UNDECLARED is the bug.
#   - `persist=True` is not yet implemented — deferred to a follow-up cycle
#     that adds the shared KV/table backing (F16 dedup dict + F8 arrester
#     override_count_today live in that follow-up per the audit).
#
# See also: `OverrideArrester._temp_arrester_override_active`
# (hvac_override.py:292-306) — the exemplar for a correct RESET decision
# with stated reason + operator-visible surfacing.


class DailyCounter:
    """Day-scoped integer counter that rolls over at date change.

    restart: RESET — in-memory display counter. The caller MUST supply a
    ``reason`` string explaining WHY reset-on-restart is safe for this
    counter (e.g. "metric-y counter, sensor re-derives within a day").
    Undeclared reset is the bug the RESTART-SAFETY-DOCTRINE-1 audit
    catalogued; this primitive prevents it at construction time.

    Attributes:
        name: identifier used only for diagnostic messages.
        reason: operator-facing justification for RESET-on-restart.

    Usage:
        self._alerts_today = DailyCounter(
            name="security.alerts_today",
            persist=False,
            reason="alert-count display metric; sensor re-derives within a day",
        )
        self._alerts_today.increment()
        attrs["alerts_today"] = self._alerts_today.value
        # Optional explicit rollover from an existing decision-cycle hook:
        self._alerts_today.rollover_if_needed()
    """

    __slots__ = ("name", "persist", "reason", "_value", "_date")

    def __init__(
        self,
        name: str,
        *,
        persist: bool = False,
        reason: str = "",
    ) -> None:
        if persist:
            # Deferred: the persist path needs a shared backing store and a
            # coordinator-lifecycle hook. Tracked in RESTART-SAFETY-DOCTRINE-1
            # follow-ups. Callers should stay on the hand-rolled path (or a
            # dedicated per-coordinator table) until the primitive lands.
            raise NotImplementedError(
                f"DailyCounter({name}): persist=True is not implemented in "
                "the tranche-1 primitive; use a dedicated per-domain table "
                "(see ac_reset_state / HVACZones.snapshot for exemplars)."
            )
        if not reason:
            raise ValueError(
                f"DailyCounter({name}): reason='' is UNDECLARED — supply a "
                "one-line justification for RESET-on-restart per "
                "RESTART-SAFETY-DOCTRINE-1."
            )
        self.name = name
        self.persist = persist
        self.reason = reason
        self._value: int = 0
        self._date: str = ""

    def _today(self) -> str:
        # Bug Class #11 (UTC vs local): use dt_util.utcnow() to match the
        # AnomalyDetector._maybe_reset_daily_counter convention this repo
        # already guards against (test_v4_6_11_dashboard_attrs.py::
        # TestD2DatetimeUtcnowFix). Aware datetime; avoids naive/aware
        # comparison TypeError at any sibling site that mixes clocks.
        return dt_util.utcnow().date().isoformat()

    def rollover_if_needed(self, today: Optional[str] = None) -> None:
        """Roll the counter over to 0 if the UTC date has changed."""
        d = today if today is not None else self._today()
        if d != self._date:
            self._value = 0
            self._date = d

    def increment(self, n: int = 1) -> None:
        """Bump the counter by ``n`` (rolls over lazily if the date changed)."""
        self.rollover_if_needed()
        self._value += n

    def reset(self) -> None:
        """Manual reset (does not touch the rollover date)."""
        self._value = 0

    @property
    def value(self) -> int:
        """Current value (rolls over lazily if the date changed)."""
        self.rollover_if_needed()
        return self._value

    def __int__(self) -> int:  # convenience for callers that int()-coerce
        return self.value

    def __repr__(self) -> str:  # pragma: no cover - diagnostic aid only
        return (
            f"DailyCounter(name={self.name!r}, value={self._value}, "
            f"date={self._date!r}, persist={self.persist})"
        )


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
        minimum_samples_by_metric: Optional[Dict[str, int]] = None,
        unwired_metric_names: Optional["frozenset[str]"] = None,
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
            unwired_metric_names: HVAC-ANOMALY-BLIND-1 residual A. Metrics
                declared on purpose without a producer. With no data they
                report coverage reason `not_wired` (a declared gap) instead of
                `never_fed` (a starved producer, i.e. a bug). Either way they
                are blind, so the sensor reads `partial`. Entries not in
                `metric_names` are dropped with a WARNING.
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
        # RESTART-SAFETY-DOCTRINE-1 F3+F4: rollover-at-midnight counter.
        # restart: RESET — display counter aggregated from anomaly_log rows
        # that DO survive restart; the "today" cardinality is re-derivable
        # from the DB if a consumer ever needs the pre-restart contribution.
        self._anomalies_today = DailyCounter(
            name=f"anomaly_detector.{coordinator_id}.anomalies_today",
            persist=False,
            reason=(
                "display counter; anomaly_log DB rows persist and hold the "
                "authoritative day-cardinality if ever needed"
            ),
        )
        # v4.6.5.3 surface fix: suppressed metrics filtered out of severity.
        self._suppressed_metric_names: "frozenset[str]" = (
            suppressed_metric_names if suppressed_metric_names is not None
            else frozenset()
        )
        # HVAC-ANOMALY-BLIND-1 D1a: per-metric minimum_samples override.
        # When a metric is absent from this dict the scalar
        # `self.minimum_samples` still applies (backward-compat default).
        # Sampling cadences differ: a daily-emit metric (short_cycle_rate:
        # 1 obs/day/zone) cannot share a maturation gate with a 5-min-tick
        # metric — 336 samples ≈ 28h for the tick cadence but 336 DAYS at
        # 1/day. See PLANNING_hvac_short_cycle_producer.md §Design Decision.
        self._minimum_samples_by_metric: Dict[str, int] = (
            dict(minimum_samples_by_metric) if minimum_samples_by_metric
            else {}
        )
        # HVAC-ANOMALY-BLIND-1 residual A: declared-unwired metrics.
        _unwired = frozenset(unwired_metric_names or ())
        _undeclared = _unwired - set(metric_names)
        if _undeclared:
            _LOGGER.warning(
                "AnomalyDetector %s: unwired_metric_names %s are not in "
                "metric_names; ignoring them",
                coordinator_id, sorted(_undeclared),
            )
        self._unwired_metric_names: "frozenset[str]" = _unwired - _undeclared
        # One-time WARNING per metric when a declared-unwired metric has data
        # (the declaration is stale). Per-detector, so no log spam.
        self._warned_unwired_but_fed: set[str] = set()
        # ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1 fix-up: one-shot WARNING
        # per detector the first time save_baselines finds _baselines_loaded
        # False (so a persistent load failure logs ONCE, not every hourly
        # periodic save). Reset to False once load recovers.
        self._warned_save_unloaded: bool = False
        # ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1 (A-LOW fix): guard against
        # overwriting stored (mature) rows with a fresh in-memory dict when
        # load_baselines() silently failed. load_baselines swallows all DB
        # errors to debug (above) — a subsequent CM-periodic save_baselines
        # would then write back the still-empty / few-sample dict and clobber
        # the authoritative rows. Default True: detectors that never call
        # load_baselines (no persistence surface) stay freely saveable; the
        # flag flips to False only when load_baselines is CALLED but fails.
        self._baselines_loaded: bool = True

    def _min_samples_for(self, metric_name: str) -> int:
        """Return the maturation gate for a metric.

        Uses the per-metric override (D1a) if configured; falls back to the
        scalar `self.minimum_samples`. Called from record_observation,
        get_learning_status, and get_status_summary.
        """
        return self._minimum_samples_by_metric.get(
            metric_name, self.minimum_samples,
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
        """Get or create a baseline for a metric+scope pair.

        WRITE PATH ONLY (record_observation). Read paths must use
        `_peek_baseline` / `_scopes_for`, which never create a row: a created
        row is a phantom `(metric, scope, 0)` that save_baselines persists,
        and a creation during save_baselines' await is the M3 race.
        """
        key = (metric_name, scope)
        if key not in self._baselines:
            self._baselines[key] = MetricBaseline(
                metric_name=metric_name,
                coordinator_id=self.coordinator_id,
                scope=scope,
            )
        return self._baselines[key]

    def _peek_baseline(
        self, metric_name: str, scope: str,
    ) -> Optional[MetricBaseline]:
        """Return the existing baseline for (metric, scope), or None. Never
        creates."""
        return self._baselines.get((metric_name, scope))

    def _scopes_for(self, metric_name: str) -> Dict[str, MetricBaseline]:
        """Return the existing baselines of one metric keyed by scope. Never
        creates."""
        return {
            s_name: b
            for (m_name, s_name), b in list(self._baselines.items())
            if m_name == metric_name
        }

    def _best_scope(
        self, metric_name: str,
    ) -> tuple[Optional[str], Optional[MetricBaseline]]:
        """The metric's existing scope with the highest sample_count; ties go
        to the lexicographically smallest scope name. (None, None) when the
        metric has no row at all (n = 0). A phantom `(metric, house, 0)` row
        can therefore never win over a fed zone row.
        """
        scopes = self._scopes_for(metric_name)
        if not scopes:
            return None, None
        s_name, b = min(
            scopes.items(), key=lambda kv: (-kv[1].sample_count, kv[0]),
        )
        return s_name, b

    def _status_metric(self, metric_name: str, scope: str) -> tuple[int, bool]:
        """(sample_count, stalled) used by the status reads.

        scope == "house" (the default and the only value production passes):
        best-scope aggregation, so a zone-fed metric counts, and the stall
        check looks at the newest sample in ANY scope. Any other explicit
        scope: exactly that scope (pre-existing semantics, minus the row
        creation).
        """
        if scope == "house":
            _s, b = self._best_scope(metric_name)
            stamps = self._scopes_for(metric_name).values()
        else:
            b = self._peek_baseline(metric_name, scope)
            stamps = [b] if b is not None else []
        n = b.sample_count if b is not None else 0
        return n, self._is_stalled(stamps)

    @staticmethod
    def _max_last_updated_dt(baselines) -> Optional[datetime]:
        """Max `last_updated` across baselines as an aware UTC datetime.

        Naive values (pre-A-M2 rows) are treated as UTC; unparseable or None
        values are skipped.
        """
        best: Optional[datetime] = None
        for b in baselines:
            raw = getattr(b, "last_updated", None)
            if not raw:
                continue
            try:
                parsed = dt_util.parse_datetime(str(raw))
            except Exception:  # noqa: BLE001 - defensive parse
                parsed = None
            if parsed is None:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if best is None or parsed > best:
                best = parsed
        return best.astimezone(timezone.utc) if best is not None else None

    @classmethod
    def _max_last_updated(cls, baselines) -> Optional[str]:
        """Display form of `_max_last_updated_dt`: aware ISO `+00:00` or None."""
        best = cls._max_last_updated_dt(baselines)
        return best.isoformat() if best is not None else None

    @classmethod
    def _is_stalled(cls, baselines) -> bool:
        """True when the newest sample is older than
        ANOMALY_LEARNING_STALL_DAYS. No parseable timestamp → False (not
        judged). Only meaningful for a below-gate metric with data."""
        newest = cls._max_last_updated_dt(baselines)
        if newest is None:
            return False
        now = dt_util.utcnow()
        if now.tzinfo is None:  # defensive: a naive clock is UTC
            now = now.replace(tzinfo=timezone.utc)
        return now - newest > timedelta(days=ANOMALY_LEARNING_STALL_DAYS)

    def get_coverage(self) -> Dict[str, Dict[str, Any]]:
        """Per declared metric: can this detector see it?

        Aggregates across scopes (no `scope` argument). Per metric returns
        `reason`, `suppressed`, `constant_baseline`, `best_scope`,
        `sample_count` (best scope) and `last_updated` (aware UTC max).

        Reasons, first match wins: ok (best n ≥ gate) → learning (0 < n <
        gate, newest sample within ANOMALY_LEARNING_STALL_DAYS) →
        not_collecting (0 < n < gate, newest sample older than that; operator
        ruling 2026-09-29) → not_wired (n == 0, declared unwired) → never_fed
        (n == 0, not declared: a starved producer). Data wins over the
        declaration: a declared-unwired metric with data gets its data reason
        plus a one-time WARNING naming the stale declaration.

        `constant_baseline` is an ANNOTATION: best-scope n ≥ gate AND the
        stored raw `variance == 0.0` exactly (never `.std`, which is floored
        at 0.1). It is not blindness — such a metric is hair-triggered.
        """
        coverage: Dict[str, Dict[str, Any]] = {}
        for metric_name in self.metric_names:
            gate = self._min_samples_for(metric_name)
            scopes = self._scopes_for(metric_name)
            best_scope, best = self._best_scope(metric_name)
            n = best.sample_count if best is not None else 0
            if n >= gate:
                reason = COVERAGE_REASON_OK
            elif n > 0:
                reason = (
                    COVERAGE_REASON_NOT_COLLECTING
                    if self._is_stalled(scopes.values())
                    else COVERAGE_REASON_LEARNING
                )
            elif metric_name in self._unwired_metric_names:
                reason = COVERAGE_REASON_NOT_WIRED
            else:
                reason = COVERAGE_REASON_NEVER_FED
            if (
                n > 0
                and metric_name in self._unwired_metric_names
                and metric_name not in self._warned_unwired_but_fed
            ):
                self._warned_unwired_but_fed.add(metric_name)
                _LOGGER.warning(
                    "AnomalyDetector %s: metric %s is declared unwired but has "
                    "data (%d samples at %s); the declaration is stale",
                    self.coordinator_id, metric_name, n, best_scope,
                )
            coverage[metric_name] = {
                "reason": reason,
                "suppressed": metric_name in self._suppressed_metric_names,
                "constant_baseline": bool(
                    best is not None and n >= gate and best.variance == 0.0
                ),
                "best_scope": best_scope,
                "sample_count": n,
                "last_updated": self._max_last_updated(scopes.values()),
            }
        return coverage

    def get_blind_metrics(
        self, coverage: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, str]:
        """{metric: reason} for every blind declared metric (metric order)."""
        cov = coverage if coverage is not None else self.get_coverage()
        return {
            m: c["reason"] for m, c in cov.items()
            if c["reason"] in BLIND_COVERAGE_REASONS
        }

    def get_coverage_state(self) -> str:
        """`partial` when any declared metric is blind, else `full`."""
        return COVERAGE_PARTIAL if self.get_blind_metrics() else COVERAGE_FULL

    def get_sensor_state(self) -> str:
        """The one anomaly-sensor state projection (replaces 5 duplicates).

        Precedence, top to bottom:
          1. worst persisted severity ≠ nominal → that severity (a persisted
             anomaly can only come from a mature metric, so it is never a
             learning artifact and is never masked);
          2. aggregate learning ∈ {insufficient_data, learning} → that value
             (`learning` only while a metric is actively collecting; a
             stalled detector aggregates to `paused` and falls through);
          3. any blind declared metric → `partial`;
          4. otherwise → `nominal`.
        Severity semantics are untouched; `partial` is not a severity.
        """
        severity = self.get_worst_severity()
        if severity != AnomalySeverity.NOMINAL:
            return severity.value
        learning = self.get_learning_status()
        learning_value = getattr(learning, "value", learning)
        if learning_value in (
            LearningStatus.INSUFFICIENT_DATA.value,
            LearningStatus.LEARNING.value,
        ):
            return learning_value
        if self.get_blind_metrics():
            return COVERAGE_PARTIAL
        return AnomalySeverity.NOMINAL.value

    def _maybe_reset_daily_counter(self) -> None:
        """Reset daily anomaly counter if date changed.

        Delegates to DailyCounter's rollover (F3+F4 via
        RESTART-SAFETY-DOCTRINE-1). Kept as a method for backward
        compatibility with existing call sites and tests.

        Bug Class #11 (UTC vs local): dt_util.utcnow() is the guard-tested
        convention here (test_v4_6_11_dashboard_attrs.py), so we compute
        the rollover key against UTC and reference dt_util.utcnow() in-body
        so the source-grep guard sees it in this method too.
        """
        today = dt_util.utcnow().date().isoformat()
        self._anomalies_today.rollover_if_needed(today)

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
        if baseline.sample_count >= self._min_samples_for(metric_name):
            z = baseline.z_score(value)
            severity = self._classify_severity(z)
            if severity != AnomalySeverity.NOMINAL:
                self._anomalies_today.increment()
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

        HVAC-ANOMALY-BLIND-1 residual A: non-creating read; for the default
        scope="house" each metric counts at its best scope (a zone-fed metric
        is no longer read as silent). See `_status_metric`.

        Operator ruling 2026-09-29: LEARNING means some metric is ACTIVELY
        collecting toward its gate. A below-gate metric with no sample within
        ANOMALY_LEARNING_STALL_DAYS is not learning. When the detector is not
        ACTIVE, nothing is collecting, but some data exists (a mature metric
        below the floor(n/2) threshold, or a stalled one), the aggregate is
        PAUSED (the pre-existing, previously unproduced enum member) — so
        the sensor projection falls through to `partial`, never `learning`.
        INSUFFICIENT_DATA keeps its meaning: no metric has any data.
        """
        active_metrics = 0
        learning_metrics = 0
        stalled_metrics = 0
        for metric_name in self.metric_names:
            n, stalled = self._status_metric(metric_name, scope)
            if n >= self._min_samples_for(metric_name):
                active_metrics += 1
            elif n > 0:
                if stalled:
                    stalled_metrics += 1
                else:
                    learning_metrics += 1

        threshold = max(1, len(self.metric_names) // 2)
        if active_metrics >= threshold:
            return LearningStatus.ACTIVE
        elif learning_metrics > 0:
            return LearningStatus.LEARNING
        elif active_metrics > 0 or stalled_metrics > 0:
            return LearningStatus.PAUSED
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
        """Return the metric name and z-score of the worst active anomaly.

        Suppressed metrics are excluded, matching get_worst_severity (only
        visible to tests and the diagnostic dump button).
        """
        persisted = self._persisted_active_anomalies()
        if not persisted:
            return ("", 0.0)
        worst = max(persisted, key=lambda a: a.z_score)
        return (worst.metric_name, worst.z_score)

    def get_status_summary(self, scope: str = "house") -> dict:
        """Return a summary of anomaly detection status for diagnostics.

        v4.5.14: top-level `metrics_active_ratio` (e.g. "2/4") and
        `metrics_silent` (list of metric names with 0 samples) make the
        dead-metric reality visible at a glance. The gate relaxation in
        v4.5.13 lets the detector report `active` when only some metrics
        have baselines; without these summary fields, a consumer
        couldn't tell which metrics were silently dead.

        HVAC-ANOMALY-BLIND-1 residual A: every read here is non-creating.
        `metrics_active_ratio` / `metrics_silent` use best-scope aggregation
        for scope="house". Additive keys: `coverage`, `metrics_blind`,
        `metrics_unwired`, `metrics_constant`, and per-metric `reason`,
        `suppressed`, `constant_baseline`, `best_scope`, `last_updated`.
        Per-metric `active` / mean / std stay requested-scope.
        """
        self._maybe_reset_daily_counter()
        active_count = 0
        silent_metrics: list[str] = []
        for metric_name in self.metric_names:
            n, _stalled = self._status_metric(metric_name, scope)
            if n >= self._min_samples_for(metric_name):
                active_count += 1
            elif n == 0:
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
            "anomalies_today": self._anomalies_today.value,
            "metrics": {},
        }
        # HVAC-ANOMALY-BLIND-1 D1b: scope-aware per-metric surface.
        # The requested `scope` (default "house") remains the top-level shape
        # for backward compat with existing dashboards and tests. For metrics
        # that also have non-`scope` baselines (e.g. zone-scoped
        # `short_cycle_rate` with scope=zone_1/zone_2/zone_3), a nested
        # `scopes` dict surfaces them — never via `_get_baseline(other_scope,
        # requested_scope)` which would fabricate an empty baseline for the
        # wrong key. Only keys already present in `self._baselines` are
        # surfaced (no side-effect creation).
        coverage = self.get_coverage()
        blind = self.get_blind_metrics(coverage)
        for metric_name in self.metric_names:
            # Non-creating: an absent requested-scope row is rendered from a
            # fresh, UNSTORED MetricBaseline (mean 0.0, std 1.0, n 0) — the
            # exact pre-cycle output, minus the insert.
            baseline = self._peek_baseline(metric_name, scope) or MetricBaseline(
                metric_name=metric_name,
                coordinator_id=self.coordinator_id,
                scope=scope,
            )
            gate = self._min_samples_for(metric_name)
            entry: Dict[str, Any] = {
                "mean": round(baseline.mean, 4),
                "std": round(baseline.std, 4),
                "sample_count": baseline.sample_count,
                "active": baseline.sample_count >= gate,
                # A-M2 (review fix-up): per-metric gate value alongside
                # the top-level scalar `minimum_samples` at :1158 — a
                # per-metric override (D1a) was invisible on the sensor
                # without this. Top-level scalar preserved unchanged.
                "minimum_samples": gate,
            }
            per_scope: Dict[str, Dict[str, Any]] = {}
            for (m_name, s_name), b in list(self._baselines.items()):
                if m_name != metric_name or s_name == scope:
                    continue
                per_scope[s_name] = {
                    "mean": round(b.mean, 4),
                    "std": round(b.std, 4),
                    "sample_count": b.sample_count,
                    "active": b.sample_count >= gate,
                    "minimum_samples": gate,
                }
            if per_scope:
                entry["scopes"] = per_scope
            cov = coverage[metric_name]
            entry["reason"] = cov["reason"]
            entry["suppressed"] = cov["suppressed"]
            entry["constant_baseline"] = cov["constant_baseline"]
            entry["best_scope"] = cov["best_scope"]
            entry["last_updated"] = cov["last_updated"]
            summary["metrics"][metric_name] = entry
        summary["coverage"] = COVERAGE_PARTIAL if blind else COVERAGE_FULL
        summary["metrics_blind"] = blind
        summary["metrics_unwired"] = [
            m for m in self.metric_names if m in self._unwired_metric_names
        ]
        summary["metrics_constant"] = [
            m for m in self.metric_names if coverage[m]["constant_baseline"]
        ]
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
        # A-LOW fix: assume load failed until it succeeds. Prevents a
        # downstream save_baselines from stamping a half-loaded or empty
        # dict over mature stored rows if the SELECT raises below.
        self._baselines_loaded = False
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
            # Successful load (including "nothing stored yet" — the SELECT
            # returning zero rows is a legitimate cold-start, not a failure):
            # enable subsequent saves.
            self._baselines_loaded = True
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
        # A-LOW guard: if load_baselines was called and silently failed,
        # the in-memory dict is NOT the authoritative state and writing it
        # back would clobber the mature stored rows with young samples.
        if not self._baselines_loaded:
            # ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1 fix-up: without a
            # discharge, one transient load failure (e.g. boot-time DB race)
            # disabled ALL subsequent saves (periodic, HVAC rollover,
            # teardown) silently until the next HA restart. Log a WARNING
            # exactly once per detector so the condition is visible, then
            # retry load_baselines in-line. load_baselines() assigns stored
            # rows into self._baselines[key]; keys that exist ONLY in memory
            # (sampled since the failed load) are preserved — only keys
            # present in BOTH get overwritten with the stored baseline, which
            # is the same end-state a normal successful boot would produce.
            if not self._warned_save_unloaded:
                _LOGGER.warning(
                    "save_baselines for %s: prior load_baselines failed; "
                    "retrying load before save (will suppress further warnings "
                    "for this detector until recovery)",
                    self.coordinator_id,
                )
                self._warned_save_unloaded = True
            await self.load_baselines()
            if not self._baselines_loaded:
                _LOGGER.debug(
                    "save_baselines skipped for %s: retry load_baselines "
                    "still failing; refusing to overwrite stored rows",
                    self.coordinator_id,
                )
                return
            # Load recovered — clear the one-shot warning latch so a FUTURE
            # failure+recovery cycle logs again.
            self._warned_save_unloaded = False

        try:
            async with database._db() as db:
                # M3 (ANOMALY-SAVE-BASELINES-DICT-MUTATION-1, folded): snapshot
                # the items — the loop awaits per row, and any key creator
                # running during an await would otherwise raise "dictionary
                # changed size during iteration" and leave a partial save.
                for _key, baseline in list(self._baselines.items()):
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

    def clear_active_anomalies_filtered(
        self,
        *,
        metric_name: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> int:
        """HVAC-ANOMALY-BLIND-1 D1c: filtered variant of
        `clear_active_anomalies`.

        Removes entries from `_active_anomalies` matching BOTH `metric_name`
        (when supplied) and `scope` (when supplied). Either filter may be
        None to be a wildcard on that axis; supplying neither is equivalent
        to the zero-arg `clear_active_anomalies` and simply drops everything
        — but the caller should just call that method in that case.

        Returns the count of entries removed.

        Why this exists as a new method (not a superset of the existing one):
        the zero-arg call has multiple call sites treating it as "reset the
        detector's memory"; changing its signature would risk silently
        widening its blast radius. This method's contract is narrow:
        contain latching for ONE (metric, scope) combination at daily
        rollover, per §Traps trap 3 of the planning doc.
        """
        if metric_name is None and scope is None:
            removed = len(self._active_anomalies)
            self._active_anomalies.clear()
            return removed
        kept: list[AnomalyRecord] = []
        removed_count = 0
        for a in self._active_anomalies:
            matches_metric = metric_name is None or a.metric_name == metric_name
            matches_scope = scope is None or a.scope == scope
            if matches_metric and matches_scope:
                removed_count += 1
                continue
            kept.append(a)
        self._active_anomalies = kept
        return removed_count


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
