"""Unified AnomalyEvent dataclass and severity vocabulary for all coordinators.

v4.6.1 D0: Replaces per-coordinator ad-hoc anomaly shapes with a single
queryable schema. Two canary emitters (energy crosscheck + bayesian anomaly
score) prove the shape before full 12-touchpoint migration in later cycles.

v4.6.3 D11: Canonical context_json key set defined here so all emit sites
build consistent payloads.  Extra coordinator-specific keys go under "extra".
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


# ============================================================================
# v4.6.3 D11 — Canonical context_json helper
# ============================================================================

def build_context_json(
    *,
    zone_id: str | None = None,
    room_id: str | None = None,
    person_id: str | None = None,
    linked_event_id: int | None = None,
    source_signal: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a canonical context_json payload for an anomaly emit.

    All emit sites (D2-D6) call this helper so the key set is consistent.
    Coordinator-specific fields go under "extra"; top-level keys are reserved.

    Canonical keys (all optional — None values omitted from output):
        zone_id          — zone identifier for location-scoped anomalies
        room_id          — room identifier
        person_id        — person identifier (person-scoped anomalies)
        linked_event_id  — FK into anomaly_log for cross-coordinator correlation
        source_signal    — HA dispatcher signal that triggered this emit,
                           e.g. "SIGNAL_SAFETY_HAZARD"

    Returns a plain dict; caller passes it to AnomalyEvent.payload.
    """
    ctx: dict[str, Any] = {}
    if zone_id is not None:
        ctx["zone_id"] = zone_id
    if room_id is not None:
        ctx["room_id"] = room_id
    if person_id is not None:
        ctx["person_id"] = person_id
    if linked_event_id is not None:
        ctx["linked_event_id"] = linked_event_id
    if source_signal is not None:
        ctx["source_signal"] = source_signal
    if extra:
        ctx["extra"] = extra
    return ctx
