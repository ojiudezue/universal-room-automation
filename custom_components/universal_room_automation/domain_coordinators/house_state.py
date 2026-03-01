"""House state machine for domain coordinators."""

from __future__ import annotations

import logging
try:
    from enum import StrEnum
except ImportError:
    # Python < 3.11 fallback
    from enum import Enum

    class StrEnum(str, Enum):
        """String enum backport for Python < 3.11."""
        pass
from typing import Final

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class HouseState(StrEnum):
    """Enumeration of house states."""

    AWAY = "away"
    ARRIVING = "arriving"
    HOME_DAY = "home_day"
    HOME_EVENING = "home_evening"
    HOME_NIGHT = "home_night"
    SLEEP = "sleep"
    WAKING = "waking"
    GUEST = "guest"
    VACATION = "vacation"


# Valid state transitions — each state maps to the set of states it can transition to
VALID_TRANSITIONS: Final[dict[HouseState, set[HouseState]]] = {
    HouseState.AWAY: {
        HouseState.ARRIVING,
        HouseState.HOME_DAY,
        HouseState.HOME_EVENING,
        HouseState.HOME_NIGHT,
        HouseState.GUEST,
        HouseState.VACATION,
    },
    HouseState.ARRIVING: {
        HouseState.HOME_DAY,
        HouseState.HOME_EVENING,
        HouseState.HOME_NIGHT,
        HouseState.AWAY,
    },
    HouseState.HOME_DAY: {
        HouseState.HOME_EVENING,
        HouseState.AWAY,
        HouseState.GUEST,
    },
    HouseState.HOME_EVENING: {
        HouseState.HOME_NIGHT,
        HouseState.AWAY,
        HouseState.GUEST,
    },
    HouseState.HOME_NIGHT: {
        HouseState.SLEEP,
        HouseState.AWAY,
    },
    HouseState.SLEEP: {
        HouseState.WAKING,
        HouseState.AWAY,  # everyone left while sleeping (unusual)
    },
    HouseState.WAKING: {
        HouseState.HOME_DAY,
        HouseState.AWAY,
    },
    HouseState.GUEST: {
        HouseState.HOME_DAY,
        HouseState.HOME_EVENING,
        HouseState.HOME_NIGHT,
        HouseState.AWAY,
    },
    HouseState.VACATION: {
        HouseState.ARRIVING,
        HouseState.AWAY,
    },
}

# Default hysteresis per state (seconds) — minimum time before a state can change
DEFAULT_HYSTERESIS: Final[dict[HouseState, int]] = {
    HouseState.AWAY: 30,        # 30s — easy to leave AWAY (entering AWAY already requires census_count==0 AND no zone occupied)
    HouseState.ARRIVING: 60,    # 1 min in ARRIVING before moving to HOME
    HouseState.HOME_DAY: 120,   # 2 min minimum in HOME_DAY
    HouseState.HOME_EVENING: 120,
    HouseState.HOME_NIGHT: 120,
    HouseState.SLEEP: 600,      # 10 min minimum in SLEEP (avoid false wakes)
    HouseState.WAKING: 60,
    HouseState.GUEST: 300,
    HouseState.VACATION: 7200,  # 2 hours minimum in VACATION
}


class HouseStateMachine:
    """Manages house state with valid transitions and hysteresis.

    The state machine enforces:
    - Only valid transitions (per VALID_TRANSITIONS)
    - Minimum dwell time per state (hysteresis) to prevent oscillation
    - Override support for manual state setting (bypasses hysteresis)
    """

    def __init__(
        self,
        initial_state: HouseState = HouseState.AWAY,
        hysteresis: dict[HouseState, int] | None = None,
    ) -> None:
        """Initialize the state machine."""
        self._state = initial_state
        self._previous_state: HouseState | None = None
        self._state_since = dt_util.utcnow()
        self._hysteresis = hysteresis or dict(DEFAULT_HYSTERESIS)
        self._override: HouseState | None = None
        self._override_since: float | None = None

    @property
    def state(self) -> HouseState:
        """Return current house state (override if active, else inferred)."""
        if self._override is not None:
            return self._override
        return self._state

    @property
    def previous_state(self) -> HouseState | None:
        """Return previous house state."""
        return self._previous_state

    @property
    def state_since(self) -> float:
        """Return timestamp when current state was entered."""
        return self._state_since.timestamp()

    @property
    def is_overridden(self) -> bool:
        """Return True if state is manually overridden."""
        return self._override is not None

    @property
    def dwell_seconds(self) -> float:
        """Return how long we've been in the current state."""
        return (dt_util.utcnow() - self._state_since).total_seconds()

    def remaining_hysteresis(self) -> float:
        """Return seconds remaining before the current state can transition."""
        min_dwell = self._hysteresis.get(self._state, 0)
        remaining = min_dwell - self.dwell_seconds
        return max(0.0, remaining)

    def can_transition(self, new_state: HouseState) -> bool:
        """Check if a transition to new_state is valid and hysteresis has elapsed."""
        if new_state == self._state:
            return False

        # Check valid transition
        valid_targets = VALID_TRANSITIONS.get(self._state, set())
        if new_state not in valid_targets:
            return False

        # Check hysteresis
        min_dwell = self._hysteresis.get(self._state, 0)
        if self.dwell_seconds < min_dwell:
            return False

        return True

    def transition(self, new_state: HouseState, trigger: str = "") -> bool:
        """Attempt a state transition.

        Returns True if the transition was accepted, False if rejected.
        """
        if not self.can_transition(new_state):
            _LOGGER.debug(
                "Rejected transition %s -> %s (trigger=%s, dwell=%.0fs)",
                self._state,
                new_state,
                trigger,
                self.dwell_seconds,
            )
            return False

        old_state = self._state
        self._previous_state = old_state
        self._state = new_state
        self._state_since = dt_util.utcnow()

        # Clear any manual override on state transition
        if self._override is not None:
            self._override = None
            self._override_since = None

        _LOGGER.info(
            "House state transition: %s -> %s (trigger=%s)",
            old_state,
            new_state,
            trigger,
        )
        return True

    def set_override(self, state: HouseState) -> None:
        """Manually override the house state.

        Bypasses transition validation and hysteresis.
        Override persists until cleared or until the next inferred transition.
        """
        self._override = state
        self._override_since = dt_util.utcnow().timestamp()
        _LOGGER.info("House state override set: %s", state)

    def clear_override(self) -> None:
        """Clear manual override, returning to inferred state."""
        if self._override is not None:
            _LOGGER.info(
                "House state override cleared (was %s, returning to %s)",
                self._override,
                self._state,
            )
            self._override = None
            self._override_since = None

    def force_state(self, new_state: HouseState, trigger: str = "") -> None:
        """Force a state change, bypassing validation and hysteresis.

        Used for emergency transitions (e.g., Safety forcing AWAY on evacuation).
        """
        old_state = self._state
        self._previous_state = old_state
        self._state = new_state
        self._state_since = dt_util.utcnow()
        self._override = None
        self._override_since = None
        _LOGGER.warning(
            "House state forced: %s -> %s (trigger=%s)",
            old_state,
            new_state,
            trigger,
        )

    def to_dict(self) -> dict:
        """Serialize state machine for diagnostics."""
        return {
            "state": self.state,
            "inferred_state": self._state,
            "previous_state": self._previous_state,
            "state_since": self._state_since.isoformat(),
            "dwell_seconds": round(self.dwell_seconds),
            "is_overridden": self.is_overridden,
            "override": self._override,
        }
