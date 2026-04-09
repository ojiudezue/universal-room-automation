"""Bayesian Predictor for Universal Room Automation v4.0.0-B1.

Dirichlet-Multinomial conjugate model for room occupancy prediction.
Predicts P(person -> room | time_bin, day_type) using historical
room transition data as prior and live transitions as observations.

Mathematical model:
- Prior: Dirichlet(alpha_1, ..., alpha_R) from room_transitions frequency
- Update: alpha_r_posterior = alpha_r_prior + weight (per observation)
- Point estimate: P(room_r) = alpha_r / sum(alphas)
- Uncertainty: Var(theta_r) = alpha_r(alpha_0 - alpha_r) / (alpha_0^2(alpha_0+1))
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

PRIOR_SCALE_FACTOR: float = 0.5
MINIMUM_ALPHA: float = 0.1
COLD_START_ALPHA: float = 1.0
COLD_START_THRESHOLD: int = 10

# Rooms to exclude from Bayesian model (non-physical locations)
EXCLUDED_ROOMS: frozenset[str] = frozenset({
    "away", "home", "unknown", "not_home",
})

# Minimum confidence for full-weight online update
MIN_CONFIDENCE_FULL_WEIGHT: float = 0.3


class TimeBin(Enum):
    """Time-of-day bins for Bayesian prediction."""

    NIGHT = 0      # 00:00-06:00
    MORNING = 1    # 06:00-09:00
    MIDDAY = 2     # 09:00-12:00
    AFTERNOON = 3  # 12:00-17:00
    EVENING = 4    # 17:00-21:00
    LATE = 5       # 21:00-24:00


class LearningStatus(Enum):
    """Learning status for a Bayesian cell."""

    INSUFFICIENT_DATA = "insufficient_data"  # <5 observations
    LEARNING = "learning"                     # 5-49 observations
    ACTIVE = "active"                         # 50+ observations


# Time bin boundaries: (start_hour, end_hour)
TIME_BIN_BOUNDARIES: dict[int, tuple[int, int]] = {
    0: (0, 6),
    1: (6, 9),
    2: (9, 12),
    3: (12, 17),
    4: (17, 21),
    5: (21, 24),
}

TIME_BIN_NAMES: dict[int, str] = {
    0: "Night",
    1: "Morning",
    2: "Midday",
    3: "Afternoon",
    4: "Evening",
    5: "Late",
}


# ============================================================================
# Data quality
# ============================================================================


@dataclass
class DataQualityReport:
    """Report on data quality for Bayesian prior initialization."""

    total_rows: int = 0
    null_rooms: int = 0
    self_transitions: int = 0
    impossible_durations: int = 0
    duplicate_timestamps: int = 0
    unknown_rooms: int = 0
    low_confidence: int = 0
    passed: int = 0

    def summary(self) -> str:
        """Return human-readable summary."""
        pct = (self.passed / self.total_rows * 100) if self.total_rows > 0 else 0
        return (
            f"B1 Data Quality: {self.total_rows} total, "
            f"{self.passed} passed ({pct:.1f}%), "
            f"excluded: null={self.null_rooms}, self={self.self_transitions}, "
            f"duration={self.impossible_durations}, dup={self.duplicate_timestamps}, "
            f"unknown={self.unknown_rooms}, low_conf={self.low_confidence}"
        )


# ============================================================================
# Main predictor
# ============================================================================


class BayesianPredictor:
    """Dirichlet-Multinomial Bayesian predictor for room occupancy.

    Internal state:
        _beliefs: maps (person_id, time_bin, day_type) -> {room_id: alpha}
        _observation_counts: real observation count per cell (excludes prior)
        _learning_suppressed: guest mode flag

    Thread safety: update() is synchronous (in-memory dict mutation).
    initialize() and save_beliefs() are async (DB I/O).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize predictor (call initialize() to load data)."""
        self.hass = hass
        # (person_id, time_bin_int, day_type_int) -> {room_id: alpha_float}
        self._beliefs: dict[tuple[str, int, int], dict[str, float]] = {}
        # Real observation count per cell (separate from prior pseudo-counts)
        self._observation_counts: dict[tuple[str, int, int], int] = {}
        # Set of all known room IDs across all cells
        self._known_rooms: set[str] = set()
        # Set of all known person IDs
        self._known_persons: set[str] = set()
        # Guest mode suppresses learning
        self._learning_suppressed: bool = False
        # Data quality report from last initialization
        self._quality_report: DataQualityReport | None = None
        # Database reference
        self._database = None
        _LOGGER.info("BayesianPredictor created (not yet initialized)")

    async def initialize(self, database) -> None:
        """Initialize from DB: load saved beliefs or build from priors.

        Args:
            database: UniversalRoomDatabase instance
        """
        self._database = database

        # Try to restore saved beliefs first
        saved = await database.load_bayesian_beliefs()
        if saved:
            self._restore_from_saved(saved)
            _LOGGER.info(
                "BayesianPredictor restored %d belief cells from DB "
                "(%d persons, %d rooms)",
                len(self._beliefs),
                len(self._known_persons),
                len(self._known_rooms),
            )
        else:
            # Cold start: build priors from room_transitions
            await self._build_priors_from_transitions(database)
            _LOGGER.info(
                "BayesianPredictor initialized from priors: %d cells, "
                "%d persons, %d rooms",
                len(self._beliefs),
                len(self._known_persons),
                len(self._known_rooms),
            )

        # Log data quality
        report = await self.scan_data_quality(database)
        self._quality_report = report
        self._cached_transition_rows = None  # Free memory after quality scan
        _LOGGER.info(report.summary())

    def _restore_from_saved(self, rows: list[dict]) -> None:
        """Restore beliefs and observation counts from DB rows."""
        self._beliefs.clear()
        self._observation_counts.clear()
        self._known_rooms.clear()
        self._known_persons.clear()

        for row in rows:
            person_id = row["person_id"]
            time_bin = row["time_bin"]
            day_type = row["day_type"]
            room_id = row["room_id"]
            alpha = row["alpha"]
            obs_count = row.get("observation_count", 0)

            key = (person_id, time_bin, day_type)
            if key not in self._beliefs:
                self._beliefs[key] = {}
                self._observation_counts[key] = 0
            self._beliefs[key][room_id] = alpha
            # observation_count is per-cell, take max across rooms
            # (all rooms in a cell share the same observation count)
            if obs_count > self._observation_counts[key]:
                self._observation_counts[key] = obs_count
            self._known_rooms.add(room_id)
            self._known_persons.add(person_id)

    async def _build_priors_from_transitions(self, database) -> None:
        """Build Dirichlet priors from historical room_transitions data."""
        self._beliefs.clear()
        self._observation_counts.clear()
        self._known_rooms.clear()
        self._known_persons.clear()

        rows = await database.get_room_transition_counts(days=90)
        if not rows:
            _LOGGER.info("No room_transitions data — starting with empty priors")
            return
        # Cache rows for data quality scan to avoid double DB fetch
        self._cached_transition_rows = rows

        # Phase 1: Aggregate counts per (person, time_bin, day_type, to_room)
        # Each row has: person_id, to_room, timestamp, confidence
        raw_counts: dict[tuple[str, int, int], dict[str, float]] = {}
        raw_cell_counts: dict[tuple[str, int, int], int] = {}
        person_global: dict[str, dict[str, float]] = {}

        for row in rows:
            person_id = row["person_id"]
            from_room = row.get("from_room", "")
            to_room = row["to_room"]
            confidence = row.get("confidence") or 0.5
            duration = row.get("duration_seconds") or 0

            # Apply all data quality filters (match scan_data_quality checks)
            if not to_room or to_room.lower() in EXCLUDED_ROOMS:
                continue
            if not from_room or from_room.lower() in EXCLUDED_ROOMS:
                continue
            if from_room == to_room:  # Self-transition
                continue
            if duration < 0 or duration > 86400:  # Impossible duration
                continue
            if confidence < MIN_CONFIDENCE_FULL_WEIGHT:
                continue

            ts_str = row.get("timestamp", "")
            try:
                if isinstance(ts_str, str):
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                else:
                    ts = ts_str
                local_ts = dt_util.as_local(ts) if ts.tzinfo else ts
            except (ValueError, TypeError):
                continue

            time_bin = _hour_to_time_bin(local_ts.hour)
            day_type = _day_type(local_ts)

            key = (person_id, time_bin, day_type)
            if key not in raw_counts:
                raw_counts[key] = {}
                raw_cell_counts[key] = 0
            raw_counts[key][to_room] = raw_counts[key].get(to_room, 0) + 1
            raw_cell_counts[key] += 1

            # Track global distribution per person
            if person_id not in person_global:
                person_global[person_id] = {}
            person_global[person_id][to_room] = (
                person_global[person_id].get(to_room, 0) + 1
            )

            self._known_rooms.add(to_room)
            self._known_persons.add(person_id)

        # Phase 2: Build Dirichlet alphas from scaled counts
        for key, room_counts in raw_counts.items():
            person_id = key[0]
            cell_total = raw_cell_counts[key]

            if cell_total < COLD_START_THRESHOLD:
                # Cold start: use person's global distribution
                global_dist = person_global.get(person_id, {})
                if global_dist:
                    global_total = sum(global_dist.values())
                    self._beliefs[key] = {
                        room: max(
                            MINIMUM_ALPHA,
                            (count / global_total) * COLD_START_ALPHA,
                        )
                        for room, count in global_dist.items()
                    }
                else:
                    # No data at all — uniform minimum
                    self._beliefs[key] = {
                        room: MINIMUM_ALPHA for room in self._known_rooms
                    }
            else:
                # Normal prior: scale counts
                self._beliefs[key] = {}
                for room, count in room_counts.items():
                    self._beliefs[key][room] = max(
                        MINIMUM_ALPHA, count * PRIOR_SCALE_FACTOR
                    )

            # Ensure all known rooms have at least MINIMUM_ALPHA
            for room in self._known_rooms:
                if room not in self._beliefs[key]:
                    self._beliefs[key][room] = MINIMUM_ALPHA

            self._observation_counts[key] = 0  # Priors don't count as observations

    @callback
    def update(
        self,
        person_id: str,
        to_room: str,
        timestamp: datetime,
        confidence: float,
    ) -> None:
        """Update beliefs with a new transition observation.

        Synchronous — only updates in-memory dicts.
        Called from TransitionDetector after each transition is logged.

        Args:
            person_id: Person who moved
            to_room: Room they moved to
            timestamp: When the transition occurred
            confidence: Transition confidence (0-1)
        """
        if self._learning_suppressed:
            _LOGGER.debug(
                "Bayesian update suppressed (guest mode): %s -> %s",
                person_id, to_room,
            )
            return

        # Filter excluded rooms
        if not to_room or to_room.lower() in EXCLUDED_ROOMS:
            return

        try:
            local_ts = dt_util.as_local(timestamp) if timestamp.tzinfo else timestamp
        except (ValueError, AttributeError):
            local_ts = dt_util.now()

        time_bin = _hour_to_time_bin(local_ts.hour)
        day_type = _day_type(local_ts)
        key = (person_id, time_bin, day_type)

        # Ensure cell exists
        if key not in self._beliefs:
            self._beliefs[key] = {
                room: MINIMUM_ALPHA for room in self._known_rooms
            }
            self._observation_counts[key] = 0

        # Ensure room exists in cell
        if to_room not in self._beliefs[key]:
            self._beliefs[key][to_room] = MINIMUM_ALPHA

        # Update alpha: full weight if confidence >= threshold, fractional otherwise
        if confidence >= MIN_CONFIDENCE_FULL_WEIGHT:
            weight = confidence
        else:
            weight = confidence * 0.5  # Fractional weight for low confidence

        self._beliefs[key][to_room] += weight
        self._observation_counts[key] = self._observation_counts.get(key, 0) + 1

        # Track new rooms and persons
        self._known_rooms.add(to_room)
        self._known_persons.add(person_id)

        # Fire signal for sensors
        from .domain_coordinators.signals import SIGNAL_BAYESIAN_UPDATED
        async_dispatcher_send(self.hass, SIGNAL_BAYESIAN_UPDATED)

        _LOGGER.debug(
            "Bayesian update: %s -> %s (bin=%d, day=%d, weight=%.2f, "
            "new_alpha=%.2f, obs=%d)",
            person_id, to_room, time_bin, day_type, weight,
            self._beliefs[key][to_room],
            self._observation_counts[key],
        )

    def predict_room(
        self,
        person_id: str,
        time_bin: int,
        day_type: int,
    ) -> dict[str, Any] | None:
        """Predict room distribution for a person at a given time context.

        Returns:
            {
                "top_room": str,
                "probability": float,
                "alternatives": [{"room": str, "probability": float}, ...],
                "confidence_interval": {"low": float, "high": float},
                "learning_status": str,
            }
            or None if no data for this cell.
        """
        key = (person_id, time_bin, day_type)
        alphas = self._beliefs.get(key)
        if not alphas:
            return None

        alpha_0 = sum(alphas.values())
        if alpha_0 == 0:
            return None

        # Compute probabilities
        probs = {
            room: alpha / alpha_0
            for room, alpha in alphas.items()
        }

        # Sort by probability descending
        sorted_probs = sorted(probs.items(), key=lambda x: x[1], reverse=True)

        top_room, top_prob = sorted_probs[0]

        # Alternatives (next 4)
        alternatives = [
            {"room": room, "probability": round(prob, 4)}
            for room, prob in sorted_probs[1:5]
        ]

        # Confidence interval for top room using Dirichlet variance
        ci = self._confidence_interval(alphas[top_room], alpha_0)

        # Learning status
        obs = self._observation_counts.get(key, 0)
        status = self._learning_status(obs)

        return {
            "top_room": top_room,
            "probability": round(top_prob, 4),
            "alternatives": alternatives,
            "confidence_interval": ci,
            "learning_status": status.value,
        }

    def predict_room_occupancy(
        self,
        room_id: str,
        time_bin: int,
        day_type: int,
    ) -> float | None:
        """Predict probability that a room will be occupied.

        Aggregates across all persons:
        P(room occupied) = 1 - product(1 - P(person_p in room))

        Returns:
            Float 0-1, or None if no data.
        """
        if not self._known_persons:
            return None

        product_not_occupied = 1.0
        has_data = False

        for person_id in self._known_persons:
            key = (person_id, time_bin, day_type)
            alphas = self._beliefs.get(key)
            if not alphas:
                continue
            alpha_0 = sum(alphas.values())
            if alpha_0 == 0:
                continue
            room_alpha = alphas.get(room_id, 0.0)
            if room_alpha <= 0:
                continue  # Person has no data for this room — skip
            p_person_in_room = room_alpha / alpha_0
            product_not_occupied *= (1.0 - p_person_in_room)
            has_data = True

        if not has_data:
            return None

        return round(1.0 - product_not_occupied, 4)

    def get_top_time_bin_for_room(
        self,
        room_id: str,
    ) -> dict[str, Any] | None:
        """Find the time bin with highest occupancy probability for a room.

        Returns:
            {
                "time_bin": int,
                "time_bin_name": str,
                "day_type": int,
                "probability": float,
                "learning_status": str,
            }
            or None if no data.
        """
        best = None
        best_prob = -1.0

        for time_bin in range(6):
            for day_type in range(2):
                prob = self.predict_room_occupancy(room_id, time_bin, day_type)
                if prob is not None and prob > best_prob:
                    best_prob = prob
                    # Get learning status from any cell in this bin
                    obs_total = 0
                    for person_id in self._known_persons:
                        key = (person_id, time_bin, day_type)
                        obs_total += self._observation_counts.get(key, 0)
                    best = {
                        "time_bin": time_bin,
                        "time_bin_name": TIME_BIN_NAMES.get(time_bin, "Unknown"),
                        "day_type": day_type,
                        "probability": round(best_prob, 4),
                        "learning_status": self._learning_status(obs_total).value,
                    }

        return best

    @callback
    def suppress_learning(self, suppressed: bool) -> None:
        """Suppress or re-enable learning (for guest mode)."""
        self._learning_suppressed = suppressed
        _LOGGER.info("Bayesian learning %s", "suppressed" if suppressed else "resumed")

    async def save_beliefs(self) -> None:
        """Persist current beliefs to database."""
        if self._database is None:
            _LOGGER.warning("Cannot save beliefs — no database reference")
            return

        rows: list[dict] = []
        now = dt_util.utcnow().isoformat()

        for (person_id, time_bin, day_type), alphas in self._beliefs.items():
            obs_count = self._observation_counts.get(
                (person_id, time_bin, day_type), 0
            )
            for room_id, alpha in alphas.items():
                rows.append({
                    "person_id": person_id,
                    "time_bin": time_bin,
                    "day_type": day_type,
                    "room_id": room_id,
                    "alpha": alpha,
                    "observation_count": obs_count,
                    "updated_at": now,
                })

        if rows:
            await self._database.save_bayesian_beliefs(rows)
            _LOGGER.debug("Saved %d Bayesian belief rows to DB", len(rows))

    async def clear_and_reinitialize(self) -> None:
        """Clear all beliefs and rebuild from room_transitions priors.

        Used by the ClearBayesianBeliefsButton.
        """
        if self._database is None:
            _LOGGER.warning("Cannot reinitialize — no database reference")
            return

        _LOGGER.info("Clearing Bayesian beliefs and reinitializing from priors")

        # Suppress learning during reinit to prevent race with update()
        was_suppressed = self._learning_suppressed
        self._learning_suppressed = True
        try:
            # Clear DB table
            await self._database.clear_bayesian_beliefs()

            # Rebuild from historical transitions
            await self._build_priors_from_transitions(self._database)

            # Re-run quality scan
            report = await self.scan_data_quality(self._database)
            self._quality_report = report
            _LOGGER.info("Reinitialized: %s", report.summary())
        finally:
            self._learning_suppressed = was_suppressed

        # Signal sensors
        from .domain_coordinators.signals import SIGNAL_BAYESIAN_UPDATED
        async_dispatcher_send(self.hass, SIGNAL_BAYESIAN_UPDATED)

    @staticmethod
    def _confidence_interval(
        alpha_r: float, alpha_0: float
    ) -> dict[str, float]:
        """Compute 95% confidence interval using Dirichlet variance.

        Var(theta_r) = alpha_r * (alpha_0 - alpha_r) / (alpha_0^2 * (alpha_0 + 1))
        """
        if alpha_0 <= 0:
            return {"low": 0.0, "high": 0.0}

        mean = alpha_r / alpha_0
        var_num = alpha_r * (alpha_0 - alpha_r)
        var_den = (alpha_0 ** 2) * (alpha_0 + 1)
        variance = var_num / var_den if var_den > 0 else 0.0
        std = math.sqrt(max(0.0, variance))

        # 95% CI approximation: mean +/- 1.96*std, clamped to [0, 1]
        low = max(0.0, mean - 1.96 * std)
        high = min(1.0, mean + 1.96 * std)
        return {"low": round(low, 4), "high": round(high, 4)}

    @staticmethod
    def _learning_status(observation_count: int) -> LearningStatus:
        """Determine learning status from observation count."""
        if observation_count >= 50:
            return LearningStatus.ACTIVE
        elif observation_count >= 5:
            return LearningStatus.LEARNING
        else:
            return LearningStatus.INSUFFICIENT_DATA

    async def scan_data_quality(self, database, rows: list[dict] | None = None) -> DataQualityReport:
        """Scan room_transitions table for data quality issues.

        Uses cached rows from prior build if available to avoid double DB fetch.
        Returns a DataQualityReport with counts per exclusion category.
        """
        report = DataQualityReport()

        # Use cached rows from _build_priors_from_transitions if available
        if rows is None:
            rows = getattr(self, "_cached_transition_rows", None)
        if rows is None:
            rows = await database.get_room_transition_counts(days=90)
        if not rows:
            return report

        report.total_rows = len(rows)
        seen_timestamps: dict[str, set[str]] = {}  # person -> set of timestamps

        for row in rows:
            person_id = row.get("person_id", "")
            from_room = row.get("from_room", "")
            to_room = row.get("to_room", "")
            confidence = row.get("confidence")
            duration = row.get("duration_seconds")
            ts_str = row.get("timestamp", "")

            # Check 1: Null/empty rooms
            if not to_room or not from_room:
                report.null_rooms += 1
                continue

            # Check 2: Self-transitions
            if from_room == to_room:
                report.self_transitions += 1
                continue

            # Check 3: Impossible durations
            if duration is not None:
                if duration < 0 or duration > 86400:
                    report.impossible_durations += 1
                    continue

            # Check 4: Duplicate timestamps
            if person_id not in seen_timestamps:
                seen_timestamps[person_id] = set()
            ts_key = str(ts_str)[:19]  # Truncate to seconds
            if ts_key in seen_timestamps[person_id]:
                report.duplicate_timestamps += 1
                continue
            seen_timestamps[person_id].add(ts_key)

            # Check 5: Unknown rooms
            if to_room.lower() in EXCLUDED_ROOMS or from_room.lower() in EXCLUDED_ROOMS:
                report.unknown_rooms += 1
                continue

            # Check 6: Low confidence
            if confidence is not None and confidence < MIN_CONFIDENCE_FULL_WEIGHT:
                report.low_confidence += 1
                continue

            report.passed += 1

        return report

    @property
    def quality_report(self) -> DataQualityReport | None:
        """Return the last data quality report."""
        return self._quality_report

    @property
    def belief_cell_count(self) -> int:
        """Number of (person, time_bin, day_type) cells."""
        return len(self._beliefs)

    @property
    def known_rooms(self) -> set[str]:
        """Set of all rooms the predictor knows about."""
        return self._known_rooms.copy()

    @property
    def known_persons(self) -> set[str]:
        """Set of all persons the predictor knows about."""
        return self._known_persons.copy()

    @property
    def is_learning_suppressed(self) -> bool:
        """Whether learning is suppressed (guest mode)."""
        return self._learning_suppressed

    # ====================================================================
    # v4.0.0-B2: Prediction sensor extensions
    # ====================================================================

    def predict_room_at_time(
        self, person_id: str, future_dt: datetime
    ) -> dict[str, Any] | None:
        """Predict room for a person at a future time.

        Convenience wrapper that converts a datetime to (time_bin, day_type)
        and delegates to predict_room().
        """
        try:
            local_dt = (
                dt_util.as_local(future_dt) if future_dt.tzinfo else future_dt
            )
        except (ValueError, AttributeError):
            local_dt = dt_util.now()
        time_bin = _hour_to_time_bin(local_dt.hour)
        day_type = _day_type(local_dt)
        return self.predict_room(person_id, time_bin, day_type)

    def predict_room_occupancy_at_time(
        self, room_id: str, future_dt: datetime
    ) -> float | None:
        """Predict room occupancy probability at a future time.

        Convenience wrapper that converts a datetime to (time_bin, day_type)
        and delegates to predict_room_occupancy().
        """
        try:
            local_dt = (
                dt_util.as_local(future_dt) if future_dt.tzinfo else future_dt
            )
        except (ValueError, AttributeError):
            local_dt = dt_util.now()
        time_bin = _hour_to_time_bin(local_dt.hour)
        day_type = _day_type(local_dt)
        return self.predict_room_occupancy(room_id, time_bin, day_type)

    def get_anomaly_score(self, room_id: str, is_occupied: bool) -> dict:
        """Check if current occupancy is anomalous vs Bayesian prediction.

        Returns a dict with:
            predicted_probability: float or None
            anomaly: bool (True if occupied but predicted < 10% and ACTIVE)
            learning_status: str
            time_bin: int
            day_type: int
        """
        now = dt_util.now()
        time_bin = _hour_to_time_bin(now.hour)
        day_type = _day_type(now)
        predicted = self.predict_room_occupancy(room_id, time_bin, day_type)

        # Aggregate learning status across persons for this cell
        statuses: list[LearningStatus] = []
        for person_id in self._known_persons:
            key = (person_id, time_bin, day_type)
            obs = self._observation_counts.get(key, 0)
            statuses.append(self._learning_status(obs))

        # Use the best (most advanced) learning status
        status_order = {
            LearningStatus.INSUFFICIENT_DATA: 0,
            LearningStatus.LEARNING: 1,
            LearningStatus.ACTIVE: 2,
        }
        best_status = max(
            statuses,
            key=lambda s: status_order.get(s, 0),
            default=LearningStatus.INSUFFICIENT_DATA,
        )

        threshold = 0.10  # Below 10% predicted = unexpected if occupied
        anomaly = (
            is_occupied
            and predicted is not None
            and predicted < threshold
            and best_status == LearningStatus.ACTIVE
        )

        return {
            "predicted_probability": predicted,
            "anomaly": anomaly,
            "learning_status": best_status.value,
            "time_bin": time_bin,
            "day_type": day_type,
        }

    async def record_prediction(
        self,
        room_id: str,
        time_bin: int,
        day_type: int,
        predicted_prob: float,
        actual_occupied: bool,
    ) -> None:
        """Record a prediction result for accuracy tracking.

        Uses the existing prediction_results table (prediction_type =
        "bayesian_occupancy").
        """
        if self._database is None:
            return
        await self._database.save_prediction_result(
            room_id=room_id,
            time_bin=time_bin,
            day_type=day_type,
            predicted_prob=predicted_prob,
            actual_occupied=1 if actual_occupied else 0,
            timestamp=dt_util.utcnow().isoformat(),
        )

    async def get_accuracy_stats(self, days: int = 7) -> dict:
        """Compute prediction accuracy over a rolling window.

        Returns:
            {
                "brier_score": float or None,
                "hit_rate": float or None (percentage),
                "total_predictions": int,
            }
        """
        if self._database is None:
            return {
                "brier_score": None,
                "hit_rate": None,
                "total_predictions": 0,
            }
        rows = await self._database.get_prediction_results(days=days)
        if not rows:
            return {
                "brier_score": None,
                "hit_rate": None,
                "total_predictions": 0,
            }

        brier_sum = 0.0
        hits = 0
        for row in rows:
            pred = row["predicted_probability"]
            actual = row["actual_occupied"]
            brier_sum += (pred - actual) ** 2
            # Hit = predicted > 0.5 and actual == 1, OR predicted <= 0.5 and actual == 0
            if (pred > 0.5 and actual == 1) or (pred <= 0.5 and actual == 0):
                hits += 1

        n = len(rows)
        return {
            "brier_score": round(brier_sum / n, 4),
            "hit_rate": round(hits / n * 100, 1),
            "total_predictions": n,
        }


# ============================================================================
# Helper functions
# ============================================================================


def _hour_to_time_bin(hour: int) -> int:
    """Convert hour (0-23) to time bin (0-5)."""
    if hour < 6:
        return 0   # NIGHT
    elif hour < 9:
        return 1   # MORNING
    elif hour < 12:
        return 2   # MIDDAY
    elif hour < 17:
        return 3   # AFTERNOON
    elif hour < 21:
        return 4   # EVENING
    else:
        return 5   # LATE


def _day_type(dt: datetime) -> int:
    """Return 0 for weekday, 1 for weekend."""
    return 1 if dt.weekday() >= 5 else 0
