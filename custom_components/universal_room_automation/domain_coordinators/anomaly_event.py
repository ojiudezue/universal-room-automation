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

# v4.7.12: StrEnum is Python 3.11+. HA-core min Python is well past that on
# live HAOS, but the URA test suite still runs against Python 3.9 in some
# environments. Mirror the back-compat shim used elsewhere in this codebase
# (see domain_coordinators/security.py:27-33, weather_manager.py:23-29).
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover — only fires on Python <3.11
    from enum import Enum as _Enum

    class StrEnum(str, _Enum):  # type: ignore[no-redef]
        """Lightweight back-compat StrEnum for Python <3.11."""

        def __str__(self) -> str:
            return str(self.value)

__all__ = [
    "AnomalySeverity",
    "AnomalyType",  # v4.7.12 D3
    "AnomalyEvent",
    "build_context_json",
    "map_diag_severity",
    # Legacy aliases — slated for removal in v5.0
    "EVENT_CLASS_POINT_IN_TIME",
    "EVENT_CLASS_REGIME_SHIFT",
    "EVENT_CLASS_HAZARD",
    "EVENT_CLASS_TRANSITION_INVALID",
]


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


# v4.6.6 D1: classifier-output → persisted-severity 1:1 mapping. Coordinator
# emit sites call `map_diag_severity()` instead of the legacy 2-way ternary
# (`_NewSev.CRITICAL if ... == "critical" else _NewSev.WARNING`) so the
# ADVISORY (z 2-3) and ALERT (z 3-4) bands persist as distinct integer values
# in `anomaly_log.severity` instead of both collapsing to WARNING. Reviewers
# A-M2 + B-M1 in the v4.6.5 Tier 2-DB review flagged the collapse.
_DIAG_TO_EVENT_SEVERITY = {
    # keys: coordinator_diagnostics.AnomalySeverity StrEnum .value strings
    "nominal":  AnomalySeverity.INFO,
    "advisory": AnomalySeverity.ADVISORY,
    "alert":    AnomalySeverity.ALERT,
    "critical": AnomalySeverity.CRITICAL,
}


def map_diag_severity(diag_sev: Any) -> "AnomalySeverity":
    """Map a coordinator_diagnostics.AnomalySeverity to the persisted IntEnum.

    Accepts either the StrEnum instance (preferred) or its `.value` string.
    Unknown inputs fall back to WARNING — same defensive default the prior
    2-way idiom produced for non-CRITICAL classifier outputs. This keeps the
    behavior for any caller that doesn't yet use the canonical scale.

    v4.6.6 review B-M1: logs a WARNING when the fallback fires so future
    classifier vocabulary drift (e.g., adding a 5th StrEnum bucket like
    "fatal") doesn't silently land as WARNING — surfaces the mismatch in
    home-assistant.log for diagnosis.

    Used by all 5 coordinator emit sites — see the v4.6.6 D1 migration in
    `docs/planning/PLANNING_v4.6.6_severity_refactor.md`.
    """
    key = getattr(diag_sev, "value", diag_sev)
    if key not in _DIAG_TO_EVENT_SEVERITY:
        import logging
        _logger = logging.getLogger(__name__)
        _logger.warning(
            "map_diag_severity: unknown classifier bucket %r, defaulting to "
            "WARNING. The coordinator_diagnostics.AnomalySeverity StrEnum "
            "may have added a new member that isn't in _DIAG_TO_EVENT_SEVERITY. "
            "Update the mapping table to preserve the new bucket's fidelity.",
            key,
        )
        return AnomalySeverity.WARNING
    return _DIAG_TO_EVENT_SEVERITY[key]


class AnomalyType(StrEnum):
    """Discriminator for the anomaly_log.anomaly_type column (v4.7.12 D1).

    Replaces the loose ``EVENT_CLASS_*`` string constants. Same persisted
    string values — only the type at the dataclass / DAO boundary changes,
    so old TEXT rows still round-trip after the v4.7.12 column rename.

    Members:
        POINT_IN_TIME — single-instant anomaly emission (default / today's
            behavior). All 11 existing point_in_time emitters land here.
        REGIME_SHIFT — sustained-state change; downstream consumers (planned
            v4.7.13+) treat this differently from point-in-time events.
        HAZARD — safety-domain anomaly with notification routing.
        TRANSITION_INVALID — house-state transition rule violation.

    StrEnum means ``AnomalyType.POINT_IN_TIME == "point_in_time"`` is True,
    so legacy code paths that compare strings continue to work. Migration
    from raw strings to typed enums is mechanical at every emit site.

    DO NOT add new members in v4.7.12. v4.7.13+ owns the next member.
    """

    POINT_IN_TIME = "point_in_time"
    REGIME_SHIFT = "regime_shift"
    HAZARD = "hazard"
    TRANSITION_INVALID = "transition_invalid"


# v4.7.12: legacy aliases — point to AnomalyType members. Existing callers
# that import EVENT_CLASS_POINT_IN_TIME continue to work because StrEnum
# members are also strings. Slated for deletion in v5.0.
EVENT_CLASS_POINT_IN_TIME = AnomalyType.POINT_IN_TIME
EVENT_CLASS_REGIME_SHIFT = AnomalyType.REGIME_SHIFT
EVENT_CLASS_HAZARD = AnomalyType.HAZARD
EVENT_CLASS_TRANSITION_INVALID = AnomalyType.TRANSITION_INVALID


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

    anomaly_type: AnomalyType
    """Broad class for retention policy and UI bucketing (v4.7.12 D1).

    v4.7.12 renamed from ``event_class: str`` to align with the database
    column and to narrow the type from str to AnomalyType (StrEnum).
    Legacy callers that pass a raw string literal still work because
    ``__post_init__`` coerces matching strings into AnomalyType members
    and raises ValueError on unknown values — drift caught at write time
    rather than at downstream consumer time.

    The legacy attribute ``event_class`` remains readable as a property
    alias for the duration of the dual-write window (v4.7.12 → v5.0).
    """

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

    def __post_init__(self) -> None:
        # v4.7.12 D1: defensive coercion. Accept legacy string emitters
        # transparently; raise on unknown values so future drift is caught
        # at write time rather than at downstream consumer time.
        #
        # v4.7.12 Reviewer C fix-up (C-M1 / Review B M-B2): explicit
        # type discrimination. Pre-fix-up, ``anomaly_type=None`` slipped
        # past ``isinstance(None, str)`` (False) and silently lived as
        # ``None`` on the dataclass, then defaulted to "point_in_time"
        # in the DAO — defeating the plan intent ("never rely on the
        # default"). New behavior:
        #   - AnomalyType  -> no-op
        #   - str          -> coerce or raise ValueError
        #   - anything else (incl. None) -> raise TypeError
        if isinstance(self.anomaly_type, AnomalyType):
            return
        if isinstance(self.anomaly_type, str):
            try:
                self.anomaly_type = AnomalyType(self.anomaly_type)
                return
            except ValueError as e:
                raise ValueError(
                    "AnomalyEvent.anomaly_type must be a member of AnomalyType "
                    f"or one of {[t.value for t in AnomalyType]!r}; "
                    f"got {self.anomaly_type!r}"
                ) from e
        raise TypeError(
            "AnomalyEvent.anomaly_type must be AnomalyType or str; "
            f"got {type(self.anomaly_type).__name__}"
        )

    @property
    def event_class(self) -> AnomalyType:
        """Legacy alias for ``anomaly_type`` (v4.7.12 dual-write window).

        Slated for removal in v5.0 alongside the ``event_class`` DB column.
        Returns the AnomalyType member; StrEnum equality with the raw string
        value preserves any legacy code path that compares to ``"point_in_time"``.
        """
        return self.anomaly_type


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
