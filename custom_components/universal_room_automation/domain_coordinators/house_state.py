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
from datetime import datetime, timezone
from typing import Any, Callable, Final, Optional

from homeassistant.util import dt as dt_util

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# --- D1 persistence constants (PLANNING house_state restart + override) ---
HOUSE_STATE_STORE_KEY: Final[str] = f"{DOMAIN}.house_state"
# C-L5: bump this when the persisted-record shape changes in an
# incompatible way (e.g. renaming/removing a field, or changing the
# semantics of an existing one). Additive fields do NOT require a bump —
# ``apply_restored`` reads by name and ignores unknown keys. On a bump,
# ``Store`` receives (version, minor_version) and either loads the old
# record or drops it per the caller's migration policy.
HOUSE_STATE_STORE_VERSION: Final[int] = 1
# Kill-switch: 0 disables restore (machine always starts AWAY).
HOUSE_STATE_RESTORE_MAX_STALE_S: Final[int] = 1800
# Kill-switch: 0 disables the periodic heartbeat save (falls back to
# change-only + stop saves).
HOUSE_STATE_HEARTBEAT_S: Final[int] = 300
# Debounced-save coalescing delay on transition-driven writes.
HOUSE_STATE_SAVE_DEBOUNCE_S: Final[float] = 1.0

# Docstring invariant (asserted by meta-test):
#   HOUSE_STATE_HEARTBEAT_S <= HOUSE_STATE_RESTORE_MAX_STALE_S / 3

# --- Operator policy decisions PENDING — each is a single-line flip ---
# (a) Does a manual override survive an HA restart?
#     Recommended default: YES (per plan F7).
HOUSE_STATE_OVERRIDE_SURVIVES_RESTART: Final[bool] = True
# (b) Does a dispatched override end HVAC arrester immune holds?
#     Current behaviour: YES (hvac_override.py sunset_immune_holds fires
#     on every SIGNAL_HOUSE_STATE_CHANGED). Documented here so it can be
#     flipped in one line if the operator rejects.
HOUSE_STATE_OVERRIDE_ENDS_ARRESTER_HOLDS: Final[bool] = True


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
        # Presence batch D1b: symmetric with HOME_DAY / HOME_EVENING —
        # infer() can propose GUEST from HOME_NIGHT when the guest-entry
        # gate arms during the pre-sleep evening window; without this the
        # proposal was silently rejected by the state machine
        # (Bug Class #53-adjacent: computed-but-not-consumed). Sleep-hours
        # suppression of guest ENTRY is preserved by the sleep-branch in
        # infer() firing SLEEP first from any HOME_* variant.
        HouseState.GUEST,
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
        # R2-2 marker: True only when the machine boots with a fresh
        # persisted state successfully restored from Store (within the
        # staleness bound). Presence uses this to defer settle-time
        # transitions ONLY on the restore path; cold boots preserve
        # today's behaviour.
        self._boot_restore_active: bool = False
        # D2 hook: manager wires an adapter that translates set/clear
        # override into dispatched SIGNAL_HOUSE_STATE_CHANGED via the
        # presence-owned helper. Machine itself does not import HA.
        # Signature: (old_effective, new_effective, trigger) -> None.
        self.on_state_change: Optional[
            Callable[[HouseState, HouseState, str], None]
        ] = None
        # Save-hook: manager wires a debounced Store save. Fired on any
        # accepted mutation (transition/force_state/set/clear override).
        self.on_persist_change: Optional[Callable[[], None]] = None

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

        # Clear any manual override on state transition. Presence's own
        # dispatch already carries the correct (old_effective -> new)
        # payload for this path, so we MUST NOT fire the D2 hook here
        # (double-dispatch guard, plan F6).
        if self._override is not None:
            self._override = None
            self._override_since = None

        _LOGGER.info(
            "House state transition: %s -> %s (trigger=%s)",
            old_state,
            new_state,
            trigger,
        )
        self._fire_persist_change()
        return True

    def set_override(self, state: HouseState) -> None:
        """Manually override the house state.

        Bypasses transition validation and hysteresis.
        Override persists until cleared or until the next inferred transition.

        Fires D2 dispatch hook iff the *effective* state changed.
        """
        old_effective = self.state  # override-aware (may equal inferred)
        self._override = state
        self._override_since = dt_util.utcnow().timestamp()
        _LOGGER.info("House state override set: %s", state)
        self._fire_persist_change()
        # F6 idempotence: if effective state did not change, do NOT dispatch.
        if old_effective != state and self.on_state_change is not None:
            try:
                self.on_state_change(old_effective, state, "override_set")
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "on_state_change hook (override_set) raised (non-fatal)",
                    exc_info=True,
                )

    def clear_override(self) -> None:
        """Clear manual override, returning to inferred state.

        Fires D2 dispatch hook iff clearing changes the *effective* state
        (i.e. inferred != cleared value). ``transition()`` performs its own
        override-reset inline without going through this method, so there
        is no double-dispatch risk here (C-L6: dead ``suppress_hook`` kwarg
        removed 2026-09-29).
        """
        if self._override is None:
            return
        cleared = self._override
        _LOGGER.info(
            "House state override cleared (was %s, returning to %s)",
            cleared,
            self._state,
        )
        self._override = None
        self._override_since = None
        self._fire_persist_change()
        # F6 idempotence: if inferred == cleared, effective state did not
        # change; do NOT dispatch.
        if cleared != self._state and self.on_state_change is not None:
            try:
                self.on_state_change(cleared, self._state, "override_clear")
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "on_state_change hook (override_clear) raised (non-fatal)",
                    exc_info=True,
                )

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
        self._fire_persist_change()

    def _fire_persist_change(self) -> None:
        cb = self.on_persist_change
        if cb is None:
            return
        try:
            cb()
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "on_persist_change hook raised (non-fatal)", exc_info=True,
            )

    # --- D1 persistence helpers ---------------------------------------
    def to_persisted_dict(self) -> dict[str, Any]:
        """Serialize for the Store payload (D1)."""
        override_val = self._override.value if self._override else None
        override_since = None
        if self._override_since is not None:
            override_since = datetime.fromtimestamp(
                self._override_since, tz=timezone.utc
            ).isoformat()
        return {
            "state": self._state.value,
            "state_since": self._state_since.isoformat(),
            "saved_at": dt_util.utcnow().isoformat(),
            "override": override_val,
            "override_since": override_since,
        }

    def apply_restored(
        self,
        data: dict[str, Any],
        *,
        max_stale_s: int = HOUSE_STATE_RESTORE_MAX_STALE_S,
        allow_override_restore: bool = HOUSE_STATE_OVERRIDE_SURVIVES_RESTART,
    ) -> tuple[bool, float, str]:
        """Restore state from a persisted record.

        Returns (restored, age_s, reason). Sets ``_boot_restore_active``
        True only on successful in-window restore (R2-2).

        F3: on restore, ``_state_since`` is re-armed to now so the first
        inference cannot bypass hysteresis via the persisted timestamp.
        """
        self._boot_restore_active = False
        if not isinstance(data, dict):
            return (False, -1.0, "no_record")
        if max_stale_s <= 0:
            return (False, -1.0, "restore_disabled")
        try:
            state_str = str(data.get("state", ""))
            saved_at_str = str(data.get("saved_at", ""))
            if not state_str or not saved_at_str:
                return (False, -1.0, "missing_field")
            new_state = HouseState(state_str)
            saved_at = dt_util.parse_datetime(saved_at_str)
            if saved_at is None:
                return (False, -1.0, "unparseable_saved_at")
            age = (dt_util.utcnow() - saved_at).total_seconds()
            # A-MED-1: reject overly-negative ages as "clock_skew". A tiny
            # negative window (a few seconds) can happen with NTP jitter
            # and is harmless — treat that as fresh. A large negative
            # window (saved_at more than the staleness horizon INTO THE
            # FUTURE) indicates a bogus clock and must not be trusted.
            if age < -float(max_stale_s):
                return (False, age, "clock_skew")
            if age < 0:
                age = 0.0
            if age > max_stale_s:
                return (False, age, "stale")
            self._state = new_state
            self._state_since = dt_util.utcnow()  # F3 re-arm
            self._previous_state = None
            self._override = None
            self._override_since = None
            if allow_override_restore:
                ov = data.get("override")
                if ov:
                    try:
                        self._override = HouseState(str(ov))
                        self._override_since = (
                            dt_util.utcnow().timestamp()
                        )
                    except ValueError:
                        _LOGGER.info(
                            "House-state restore: dropping bad override "
                            "value %r",
                            ov,
                        )
            self._boot_restore_active = True
            return (True, age, "ok")
        except (ValueError, TypeError, KeyError) as err:
            return (False, -1.0, f"corrupt: {err.__class__.__name__}")

    @property
    def boot_restore_active(self) -> bool:
        """R2-2 marker — True only on successful in-window restore."""
        return self._boot_restore_active

    def clear_boot_restore_active(self) -> None:
        """Called by presence after the R2-1 reconciliation tick."""
        self._boot_restore_active = False

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
