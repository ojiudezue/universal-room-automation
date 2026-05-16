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

    v4.6.6 — expanded from 3 buckets to 5 to preserve fidelity from the
    internal coordinator_diagnostics.AnomalySeverity (NOMINAL / ADVISORY /
    ALERT / CRITICAL) classifier through to the persisted anomaly_log row.
    Previously every emit site collapsed ADVISORY and ALERT into WARNING,
    making severity-grouped analytics unable to tell them apart.

    Sort order is preserved: higher integer value = more severe. Code that
    filters with `severity >= N` continues to work for INFO/WARNING; the
    CRITICAL threshold moves from 2 to 4, so any caller hardcoding the
    integer 2 to mean CRITICAL must use the enum symbol instead.
    """

    INFO = 0       # Observation worth recording; no action required
    WARNING = 1    # Unexpected; caller should act on this; cleanable
    ADVISORY = 2   # z-score 2.0-3.0 — early signal, watch but no alert
    ALERT = 3      # z-score 3.0-4.0 — notable, warrants attention
    CRITICAL = 4   # z-score > 4.0 / urgent; usually wires NM notification


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

    v4.6.3 fix (B1/A4): metric values (observed_value, expected_mean,
    expected_std, z_score, sample_size) are now explicit top-level fields on
    this dataclass so save_anomaly_event() can read them directly — resolving
    the sentinel-0.0 regression where build_context_json buried them under
    payload["extra"] while the DAO read from payload top-level.

    Callers that have no natural metric value (binary hazards, correlation
    rows) leave the defaults (0.0 / 0).  Emit sites with real metric values
    from AnomalyRecord MUST pass them as kwargs.

    context_json (payload) is used only for categorical / relational keys:
    zone_id, room_id, person_id, linked_event_id, source_signal, and
    coordinator-specific "extra" keys.  Metric fields MUST NOT be duplicated
    there — save_anomaly_event() reads from these dataclass fields directly.
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

    payload: dict[str, Any] = field(default_factory=dict)
    """Categorical/relational context only: zone_id, room_id, person_id,
    linked_event_id, source_signal, extra coordinator-specific keys.
    Do NOT put metric values here — use the explicit fields below."""

    # --- Metric fields (v4.6.3 B1/A4 fix) ---
    # These map directly to anomaly_log NOT NULL columns.  Emit sites that
    # carry real AnomalyRecord values MUST populate these.  Emit sites for
    # binary/correlation events leave the defaults.
    observed_value: float = 0.0
    """Observed metric value (e.g. count, ratio, sensor reading)."""

    expected_mean: float = 0.0
    """Baseline mean for the metric over the training window."""

    expected_std: float = 0.0
    """Baseline standard deviation for the metric."""

    z_score: float = 0.0
    """Standardised distance from mean: (observed - mean) / std."""

    sample_size: int = 0
    """Number of historical observations used to compute the baseline."""

    # --- Optional relational / lifecycle fields ---
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

    IMPORTANT — metric fields (observed_value, expected_mean, expected_std,
    z_score, sample_size) MUST NOT go into "extra".  They belong on the
    AnomalyEvent dataclass fields so save_anomaly_event() can read them
    directly into the NOT NULL columns.  Putting them under "extra" causes
    the DAO to silently write 0.0 sentinels (B1/A4 regression fixed in
    v4.6.3).  Pass coordinator-specific non-metric context under "extra".

    Returns a plain dict; caller passes it to AnomalyEvent(payload=...).
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
