"""Unified AnomalyEvent dataclass and severity vocabulary for all coordinators.

v4.6.1 D0: Replaces per-coordinator ad-hoc anomaly shapes with a single
queryable schema. Two canary emitters (energy crosscheck + bayesian anomaly
score) prove the shape before full 12-touchpoint migration in later cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class AnomalySeverity(IntEnum):
    """Unified severity scale across all coordinators.

    Replaces 8 different severity vocabularies found in the v4.5.0 survey.
    Stored as integer in DB; human-readable label available via .name.
    """

    INFO = 0      # Observation worth recording; no action required
    WARNING = 1   # Unexpected; caller should act on this; cleanable
    CRITICAL = 2  # Urgent; usually wires NM notification


# Valid event_class literal values. Enforced by convention; a StrEnum would
# add import complexity with no runtime benefit at this cycle's scope.
EVENT_CLASS_POINT_IN_TIME = "point_in_time"
EVENT_CLASS_REGIME_SHIFT = "regime_shift"
EVENT_CLASS_HAZARD = "hazard"
EVENT_CLASS_TRANSITION_INVALID = "transition_invalid"


@dataclass
class AnomalyEvent:
    """Unified anomaly representation for all coordinators.

    All fields map 1:1 to anomaly_log columns added in the v4.6.1 migration.
    `detected_at` is a UTC ISO string; callers produce it via
    dt_util.utcnow().isoformat() to avoid HA import at module level.
    """

    coordinator: str
    """Coordinator that detected the anomaly: "energy" | "person" |
    "safety" | "hvac" | "bayesian" | "circuit" | "transit"."""

    type: str
    """Namespaced discriminator, e.g. "energy.crosscheck_divergence" or
    "bayesian.prediction_anomaly". Used for filtering without event_class."""

    severity: AnomalySeverity
    """INFO | WARNING | CRITICAL — single enum, stored as INT in DB."""

    event_class: str
    """Broad class for retention policy and UI bucketing.
    One of EVENT_CLASS_* constants above."""

    detected_at: str
    """UTC ISO timestamp string of first detection."""

    payload: dict[str, Any]
    """Type-specific structured detail. JSON-serialised when written to DB."""

    recovery_at: str | None = None
    """UTC ISO timestamp when the anomaly resolved; None while active."""

    entity_id: str | None = None
    """HA entity_id if the anomaly is tied to a specific entity."""

    room_id: str | None = None
    """Room identifier for location-scoped anomalies."""

    person_id: str | None = None
    """Person identifier for person-scoped anomalies (e.g. regime shifts)."""

    correlation_id: str | None = None
    """Optional UUID linking related cross-coordinator anomalies."""
