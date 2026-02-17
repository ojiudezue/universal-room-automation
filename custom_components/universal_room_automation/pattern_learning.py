"""Pattern learning for Universal Room Automation v3.3.1.4.

Simplified frequency-based pattern learning with multi-step prediction.
Defers complex time-of-day and routine detection to v4.0.

v3.3.1.4: Fixed timestamp parsing - SQLite returns strings, not datetime objects
"""

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class PatternLearner:
    """Learn movement patterns using frequency-based analysis.
    
    v3.3.0 APPROACH (Simplified):
    - All-time frequency counting (no time-of-day segmentation)
    - Multi-step path prediction (2-3 rooms ahead)
    - Confidence scoring (sample size adjusted)
    - Alternative predictions (top 3 options)
    
    DEFERRED TO v4.0:
    - Time-of-day awareness
    - Routine detection/classification
    - Bayesian inference
    """
    
    # Pattern learning parameters
    MIN_SAMPLES_LOW = 5
    MIN_SAMPLES_MEDIUM = 10
    MIN_SAMPLES_HIGH = 20
    DEFAULT_LEARNING_DAYS = 30
    MAX_PREDICTION_STEPS = 3
    
    def __init__(self, hass: HomeAssistant, database) -> None:
        """Initialize pattern learner."""
        self.hass = hass
        self.database = database
        
        # Cache patterns per person (refreshed periodically)
        self._pattern_cache: dict[str, dict[str, Any]] = {}
        self._cache_timestamp: dict[str, datetime] = {}
        self._cache_ttl = timedelta(hours=1)  # Refresh cache hourly
        
        _LOGGER.info("PatternLearner initialized")
    
    async def analyze_patterns(
        self,
        person_id: str,
        days: int = DEFAULT_LEARNING_DAYS
    ) -> dict[str, Any]:
        """Analyze last N days of transitions for all-time patterns.
        
        Returns:
            {
                "transition_counts": {(from, to): count},
                "sequences": {(room1, room2, room3): count},
                "total_samples": int
            }
        """
        # Get transitions from database
        transitions = await self.database.get_transitions(
            person_id=person_id,
            days=days
        )
        
        if not transitions:
            _LOGGER.debug(f"No transitions found for {person_id}")
            return {
                "transition_counts": {},
                "sequences": {},
                "total_samples": 0
            }
        
        # Build frequency map of all transitions (no time segmentation)
        transition_counts = {}
        for trans in transitions:
            key = (trans["from_room"], trans["to_room"])
            transition_counts[key] = transition_counts.get(key, 0) + 1
        
        # Build multi-step sequences (2-3 rooms)
        sequences = self._build_sequences(transitions, max_length=self.MAX_PREDICTION_STEPS)
        
        return {
            "transition_counts": transition_counts,
            "sequences": sequences,
            "total_samples": len(transitions)
        }
    
    def _build_sequences(
        self,
        transitions: list[dict[str, Any]],
        max_length: int = 3
    ) -> dict[tuple, int]:
        """Build multi-step sequences from transitions.
        
        Args:
            transitions: List of transition dicts
            max_length: Maximum sequence length (rooms in path)
            
        Returns:
            {(room1, room2, room3): count}
        """
        sequences = Counter()
        
        # Sort transitions by timestamp to ensure correct order
        sorted_transitions = sorted(transitions, key=lambda t: t["timestamp"])
        
        # Sliding window over transitions
        for i in range(len(sorted_transitions) - max_length + 1):
            window = sorted_transitions[i:i + max_length]
            
            # Check if transitions are reasonably close in time
            # Skip if gap between transitions is > 2 hours
            time_gaps = []
            for j in range(len(window) - 1):
                t1 = window[j]["timestamp"]
                t2 = window[j + 1]["timestamp"]
                # Parse timestamps if they're strings (from SQLite)
                if isinstance(t1, str):
                    t1 = datetime.fromisoformat(t1.replace("Z", "+00:00"))
                if isinstance(t2, str):
                    t2 = datetime.fromisoformat(t2.replace("Z", "+00:00"))
                gap = (t2 - t1).total_seconds() / 3600  # hours
                time_gaps.append(gap)
            
            if max(time_gaps) > 2:
                continue  # Skip this sequence - transitions too far apart
            
            # Extract room sequence
            seq = [window[0]["from_room"]] + [t["to_room"] for t in window]
            sequences[tuple(seq)] += 1
        
        return dict(sequences)
    
    async def predict_next_room(
        self,
        person_id: str,
        current_room: str
    ) -> Optional[dict[str, Any]]:
        """Predict next room(s) with multi-step lookahead.
        
        Returns:
            {
                "next_room": "Bathroom",
                "confidence": 0.73,
                "sample_size": 34,
                "reliability": "high",  # Based on sample size
                "alternatives": [
                    {"room": "Kitchen", "confidence": 0.15},
                    {"room": "Office", "confidence": 0.08}
                ],
                "predicted_path": ["Bathroom", "Kitchen"]  # Multi-step
            }
        """
        _LOGGER.debug(
            "Predicting next room for %s from %s",
            person_id, current_room
        )
        
        # Get cached patterns or analyze fresh
        patterns = await self._get_patterns(person_id)
        
        if not patterns or patterns["total_samples"] == 0:
            _LOGGER.debug(
                "No patterns for %s (samples=%d)",
                person_id, patterns.get("total_samples", 0) if patterns else 0
            )
            return None
        
        _LOGGER.debug(
            "Analyzing patterns for %s: %d total samples",
            person_id, patterns["total_samples"]
        )
        
        # Find all transitions from current room
        predictions = {}
        sample_sizes = {}
        
        for (from_room, to_room), count in patterns["transition_counts"].items():
            if from_room == current_room:
                predictions[to_room] = predictions.get(to_room, 0) + count
                sample_sizes[to_room] = sample_sizes.get(to_room, 0) + count
        
        # Normalize to probabilities
        total = sum(predictions.values())
        if total == 0:
            _LOGGER.debug(
                "No transitions from %s found for %s",
                current_room, person_id
            )
            return None
        
        probabilities = {
            room: count / total 
            for room, count in predictions.items()
        }
        
        # Sort by probability
        sorted_predictions = sorted(
            probabilities.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        if not sorted_predictions:
            return None
        
        # Primary prediction
        next_room, confidence = sorted_predictions[0]
        sample_size = sample_sizes[next_room]
        
        # Calculate reliability based on sample size
        reliability = self._calculate_reliability(sample_size)
        
        # Alternative predictions (top 3)
        alternatives = [
            {"room": room, "confidence": round(conf, 2)}
            for room, conf in sorted_predictions[1:4]  # Next 3
        ]
        
        # Multi-step prediction (predict path 2-3 rooms ahead)
        predicted_path = self._predict_multi_step(
            current_room,
            patterns,
            steps=2
        )
        
        _LOGGER.info(
            "Prediction for %s from %s: %s (confidence=%.2f, samples=%d, reliability=%s)",
            person_id, current_room, next_room, confidence, sample_size, reliability
        )
        
        if alternatives:
            _LOGGER.debug(
                "Alternatives: %s",
                ", ".join([f"{a['room']}({a['confidence']:.2f})" for a in alternatives[:2]])
            )
        
        return {
            "next_room": next_room,
            "confidence": round(confidence, 2),
            "sample_size": sample_size,
            "reliability": reliability,
            "alternatives": alternatives,
            "predicted_path": predicted_path
        }
    
    def _calculate_reliability(self, sample_size: int) -> str:
        """Calculate reliability rating based on sample size."""
        if sample_size >= self.MIN_SAMPLES_HIGH:
            return "high"
        elif sample_size >= self.MIN_SAMPLES_MEDIUM:
            return "medium"
        elif sample_size >= self.MIN_SAMPLES_LOW:
            return "low"
        else:
            return "very_low"
    
    def _predict_multi_step(
        self,
        current_room: str,
        patterns: dict[str, Any],
        steps: int = 2
    ) -> list[str]:
        """Predict likely path for next N steps.
        
        Example: Current = "Bedroom"
        Returns: ["Bathroom", "Kitchen"] (most likely 2-step path)
        """
        path = []
        room = current_room
        
        for _ in range(steps):
            # Find most likely next room
            next_predictions = {}
            
            for (from_room, to_room), count in patterns["transition_counts"].items():
                if from_room == room:
                    next_predictions[to_room] = next_predictions.get(to_room, 0) + count
            
            if not next_predictions:
                break
            
            # Get highest probability room
            next_room = max(next_predictions.items(), key=lambda x: x[1])[0]
            
            # Avoid loops (don't predict going back to same room)
            if next_room == current_room or next_room in path:
                break
            
            path.append(next_room)
            room = next_room
        
        return path
    
    async def _get_patterns(self, person_id: str) -> dict[str, Any]:
        """Get patterns for person (cached or fresh)."""
        now = dt_util.now()
        
        # Check cache
        if person_id in self._pattern_cache:
            cache_age = now - self._cache_timestamp.get(person_id, now)
            if cache_age < self._cache_ttl:
                return self._pattern_cache[person_id]
        
        # Analyze fresh patterns
        patterns = await self.analyze_patterns(person_id)
        
        # Update cache
        self._pattern_cache[person_id] = patterns
        self._cache_timestamp[person_id] = now
        
        return patterns
    
    async def get_common_paths(
        self,
        person_id: str,
        min_occurrences: int = 3
    ) -> list[dict[str, Any]]:
        """Get most common movement paths for person.
        
        Returns:
            [
                {
                    "path": ["Bedroom", "Bathroom", "Kitchen"],
                    "count": 15,
                    "frequency": 0.25
                },
                ...
            ]
        """
        patterns = await self._get_patterns(person_id)
        
        if not patterns or not patterns["sequences"]:
            return []
        
        total_sequences = sum(patterns["sequences"].values())
        
        # Filter and sort sequences
        common_paths = []
        for seq, count in patterns["sequences"].items():
            if count >= min_occurrences:
                common_paths.append({
                    "path": list(seq),
                    "count": count,
                    "frequency": round(count / total_sequences, 2)
                })
        
        # Sort by count (most common first)
        common_paths.sort(key=lambda x: x["count"], reverse=True)
        
        return common_paths
    
    def clear_cache(self, person_id: Optional[str] = None) -> None:
        """Clear pattern cache for person (or all)."""
        if person_id:
            self._pattern_cache.pop(person_id, None)
            self._cache_timestamp.pop(person_id, None)
        else:
            self._pattern_cache.clear()
            self._cache_timestamp.clear()
        
        _LOGGER.debug(f"Pattern cache cleared for {person_id or 'all'}")
