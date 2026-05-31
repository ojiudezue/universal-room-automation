"""Presence Coordinator — house state inference and zone presence tracking.

Subscribes to Census updates, room occupancy sensors, BLE person tracking,
and zone camera detection. Infers house state via StateInferenceEngine.
Publishes SIGNAL_HOUSE_STATE_CHANGED.

v3.6.0-c1: Initial implementation with 3-tier zone presence signals.

Signal tiers for zone presence (any one sufficient for 'occupied'):
  1. Room occupancy sensors (mmWave/PIR) — via entity registry area_id
  2. Zone camera person/motion detection — via CameraIntegrationManager
  3. Bermuda BLE person location — via person_coordinator

Camera integration hardened from camera_census.py lessons:
  - Entity availability guards (unavailable/unknown states)
  - Entity registry for camera discovery (not substring matching)
  - Graceful degradation when sensors go offline
  - Camera detection timeout (person seen → zone occupied for N seconds)
  - try/except around all state reads
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_AREA_ID,
    CONF_ZONE_ROOMS,
    DIAGNOSTICS_SCOPE_HOUSE,
    DOMAIN,
)
from .base import BaseCoordinator, CoordinatorAction, Intent
from .coordinator_diagnostics import (
    AnomalyDetector,
    DecisionLog,
)
from .house_state import HouseState, HouseStateMachine
from .signals import (
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_CENSUS_UPDATED,
    SIGNAL_PERSON_ARRIVING,
)

_LOGGER = logging.getLogger(__name__)

# Camera detection timeout: after person/motion goes off, zone stays occupied
# for this duration before reverting to away. Prevents flapping.
_CAMERA_OCCUPANCY_TIMEOUT_SECONDS = 300  # 5 minutes

# States that mean an entity is not providing real data
_UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})

# v4.6.5.1 P2: Module-level suppression registry for presence. Companion to
# PresenceCoordinator.PRESENCE_METRICS (defined as a class attribute on the
# coordinator). Every metric in PRESENCE_METRICS must be EITHER wired (have
# a record_observation call in this file with a downstream store_event +
# activity_logger.log emit) OR listed here with a comment explaining why.
# Introspected by the parametric meta-test in test_v465_observability_gap.py.
#
# Reasons each entry is suppressed:
# - census_count (suppressed in v4.6.3.3): low-cardinality int 0..N, mostly
#   0 during sleep/away. Z-score persistence produced 1825 anomaly_log
#   emits in 24h on the live system. record_observation kept for in-memory
#   anomaly counter; persistence (store_event + activity_logger.log) stripped.
# - zone_occupied_count (suppressed in v4.6.3.1): binary 0/1 per zone per
#   inference cycle. Z-score on binary input is degenerate — rarely-occupied
#   zones produce z >= 4 on every "occupied=1.0" tick. Produced 2117 emits
#   in 3h post-v4.6.3 deploy. Same treatment as census_count.
PRESENCE_SUPPRESSED_FROM_PERSISTENCE: frozenset[str] = frozenset({
    "census_count",
    "zone_occupied_count",
})


# ============================================================================
# v4.7.15 D1: Bug Class #48 shared veto helper — types
# ============================================================================
#
# The helper unifies the trust-hierarchy pattern shipped ad-hoc in v4.7.13
# (zone aggregator, scope="zone_aggregator" SLEEP) and v4.7.14 (house
# inference, scope="house_inference" AWAY). Future cycles plug additional
# patterns by extending should_veto_due_to_reliable_signals() — no new files,
# no callable proliferation.
#
# Conservative bias is preserved: the default fall-through returns fired=False,
# so adding a new caller without a matching pattern is a no-op.

# v4.7.15 D2 / D3: thresholds shared by helper patterns. Module-level so tests
# and operator tuning can introspect them without instantiating a coordinator.
_NONSLEEP_QUIET_THRESHOLD_SECONDS = 300  # 5 min — bridge structural degeneration
_WAKING_SUSTAINED_THRESHOLD_SECONDS = 90  # ≥3 Frigate confirmations at 15-30s cadence


@dataclass(frozen=True)
class ReliableSignal:
    """A reliable, persistent presence signal (person tracker, BLE, zone_persons).

    kind: one of "person_tracker_away", "person_tracker_home",
          "zone_persons_home", "ble_proximity_present", "ble_proximity_absent".
    value: truthiness of the signal at evaluation time.
    """

    kind: str
    value: bool


@dataclass(frozen=True)
class TransientSignal:
    """A transient presence signal (camera burst, mmWave bounce, PIR).

    kind: one of "camera_person_detected", "mmwave_occupied", "pir_motion",
          "unidentified_person_count".
    count: numeric quantity (1/0 for boolean signals, N for unidentified).
    """

    kind: str
    count: int


@dataclass(frozen=True)
class VetoDecision:
    """Result of a Bug Class #48 transient-vs-reliable arbitration.

    fired: True iff the reliable signal vetoed the transient evidence.
    confidence: 0.0-1.0 confidence in the vetoed conclusion (only meaningful
                when fired=True). Mirrors the 1.0=good / 0.0=bad scale used
                by inference_engine.confidence and signal_consensus.
    reason: Short human-readable reason for activity-log + diagnostics.
            Empty string when fired=False.
    scope: The state_context scope the decision was evaluated against.
           Empty string when no scope was provided.
    """

    fired: bool
    confidence: float
    reason: str
    scope: str = ""


# ============================================================================
# Zone Presence
# ============================================================================


class ZonePresenceMode:
    """Zone presence mode constants."""

    AWAY = "away"
    OCCUPIED = "occupied"
    SLEEP = "sleep"
    UNKNOWN = "unknown"
    AUTO = "auto"  # Used in select entity to mean "clear override"

    ALL_MODES = [AWAY, OCCUPIED, SLEEP, UNKNOWN]
    OVERRIDE_OPTIONS = [AUTO, AWAY, OCCUPIED, SLEEP]


class ZonePresenceTracker:
    """Tracks presence for a single zone using room sensors, cameras, and BLE.

    Three signal tiers (any one is sufficient for 'occupied'):
    1. Room occupancy sensors (mmWave/PIR) — discovered via entity registry area_id
    2. Zone camera person/motion detection — discovered via CameraIntegrationManager
    3. Bermuda BLE person location — read from person_coordinator

    Camera signals hold the zone occupied for _CAMERA_OCCUPANCY_TIMEOUT_SECONDS
    after the last detection, preventing flapping when cameras briefly lose sight.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_name: str,
        room_names: List[str],
    ) -> None:
        self.hass = hass
        self.zone_name = zone_name
        self.room_names = room_names
        self._override: Optional[str] = None
        self._has_sensors: bool = False
        self._room_occupied: Dict[str, bool] = {}
        self._camera_occupied: Dict[str, bool] = {}  # entity_id -> detection active
        self._camera_last_seen: Dict[str, datetime] = {}  # entity_id -> last detection time
        self._ble_occupied: bool = False
        self._last_activity: Optional[datetime] = None
        self._unsub_listeners: list = []
        # Track which signal tiers are available
        self._has_room_sensors: bool = False
        self._has_camera_sensors: bool = False
        self._has_ble_sensors: bool = False
        # Track entity_id -> room_name for reverse lookup
        self._entity_to_room: Dict[str, str] = {}
        # Track camera entity_ids belonging to this zone
        self._camera_entity_ids: Set[str] = set()
        # v3.19.0: Face-confirmed arrival tracking
        self._last_face_recognized: str = ""
        self._last_face_time: Optional[datetime] = None
        self._face_arrivals_today: int = 0

    @property
    def mode(self) -> str:
        """Return current zone presence mode."""
        if self._override is not None:
            return self._override
        return self._derived_mode

    @property
    def _derived_mode(self) -> str:
        """Derive zone mode from all signal tiers.

        v3.6.0.2: BLE (Tier 3) no longer gated by _has_sensors.
        BLE person tracking is the most reliable signal and should
        always determine zone state when available.
        """
        # Tier 3 first: BLE person location (always available, most reliable)
        if self._ble_occupied:
            return ZonePresenceMode.OCCUPIED

        # Tiers 1 & 2 require sensor discovery
        if self._has_sensors:
            # Tier 1: Room occupancy sensors
            if any(self._room_occupied.values()):
                return ZonePresenceMode.OCCUPIED

            # Tier 2: Camera person/motion detection (with timeout)
            if self._any_camera_occupied():
                return ZonePresenceMode.OCCUPIED

            return ZonePresenceMode.AWAY

        # No sensors discovered and no BLE — still report away if BLE
        # has ever updated (meaning the zone is known to the system)
        if self._has_ble_sensors:
            return ZonePresenceMode.AWAY

        return ZonePresenceMode.UNKNOWN

    def _any_camera_occupied(self) -> bool:
        """Check if any camera signal indicates occupancy (with timeout)."""
        if not self._camera_last_seen:
            return False

        now = dt_util.utcnow()
        timeout = timedelta(seconds=_CAMERA_OCCUPANCY_TIMEOUT_SECONDS)

        for entity_id, last_seen in self._camera_last_seen.items():
            # Currently detecting OR within timeout window
            if self._camera_occupied.get(entity_id, False):
                return True
            if (now - last_seen) < timeout:
                return True

        return False

    @property
    def is_overridden(self) -> bool:
        """Return True if zone mode is manually overridden."""
        return self._override is not None

    @property
    def has_sensors(self) -> bool:
        """Return True if zone has at least one sensor of any tier."""
        return self._has_sensors

    def set_override(self, mode: str) -> None:
        """Set a manual override for this zone."""
        if mode == ZonePresenceMode.AUTO:
            self.clear_override()
        else:
            self._override = mode

    def clear_override(self) -> None:
        """Clear manual override."""
        self._override = None

    def update_room_occupancy(self, room_name: str, occupied: bool) -> None:
        """Update occupancy state for a room in this zone."""
        if room_name in self.room_names:
            self._room_occupied[room_name] = occupied
            self._has_sensors = True
            self._has_room_sensors = True
            if occupied:
                self._last_activity = dt_util.utcnow()
                # Auto-resume: if override is AWAY but we detect presence, clear it
                if self._override == ZonePresenceMode.AWAY:
                    _LOGGER.info(
                        "Zone %s: auto-resuming from AWAY override — presence detected in %s",
                        self.zone_name, room_name,
                    )
                    self.clear_override()

    def update_camera_detection(self, entity_id: str, detected: bool) -> None:
        """Update camera person/motion detection for this zone.

        When detected=True, records timestamp for timeout-based occupancy.
        When detected=False, the timeout keeps the zone occupied for
        _CAMERA_OCCUPANCY_TIMEOUT_SECONDS before reverting to away.
        """
        self._camera_occupied[entity_id] = detected
        self._has_sensors = True
        self._has_camera_sensors = True
        if detected:
            self._camera_last_seen[entity_id] = dt_util.utcnow()
            self._last_activity = dt_util.utcnow()
            # Auto-resume from AWAY override on camera detection
            if self._override == ZonePresenceMode.AWAY:
                _LOGGER.info(
                    "Zone %s: auto-resuming from AWAY override — camera detection on %s",
                    self.zone_name, entity_id,
                )
                self.clear_override()

    def update_ble_presence(self, has_persons: bool) -> None:
        """Update BLE-based person presence in this zone."""
        self._ble_occupied = has_persons
        if has_persons:
            self._has_sensors = True
            self._has_ble_sensors = True
            self._last_activity = dt_util.utcnow()
            if self._override == ZonePresenceMode.AWAY:
                _LOGGER.info(
                    "Zone %s: auto-resuming from AWAY override — BLE presence detected",
                    self.zone_name,
                )
                self.clear_override()

    def set_sleep(self, sleeping: bool) -> None:
        """Set sleep mode (driven by house state, not zone sensors)."""
        if sleeping and self._override is None:
            # Only set sleep if not manually overridden
            self._override = ZonePresenceMode.SLEEP
        elif not sleeping and self._override == ZonePresenceMode.SLEEP:
            # Clear sleep override when house exits sleep
            self._override = None

    def mark_has_sensors(self) -> None:
        """Mark that this zone has at least one sensor."""
        self._has_sensors = True

    def register_entity(self, entity_id: str, room_name: str) -> None:
        """Register an entity_id → room_name mapping for this zone."""
        self._entity_to_room[entity_id] = room_name
        self._has_sensors = True
        self._has_room_sensors = True

    def register_camera(self, entity_id: str) -> None:
        """Register a camera entity_id for this zone."""
        self._camera_entity_ids.add(entity_id)
        self._has_sensors = True
        self._has_camera_sensors = True

    def to_dict(self) -> dict:
        """Serialize for diagnostics."""
        return {
            "zone_name": self.zone_name,
            "mode": self.mode,
            "derived_mode": self._derived_mode,
            "is_overridden": self.is_overridden,
            "override": self._override,
            "has_sensors": self._has_sensors,
            "signal_tiers": {
                "room_sensors": self._has_room_sensors,
                "camera_sensors": self._has_camera_sensors,
                "ble_sensors": self._has_ble_sensors,
            },
            "rooms": dict(self._room_occupied),
            "cameras": {
                eid: {
                    "detecting": self._camera_occupied.get(eid, False),
                    "last_seen": (
                        self._camera_last_seen[eid].isoformat()
                        if eid in self._camera_last_seen
                        else None
                    ),
                }
                for eid in self._camera_entity_ids
            },
            "ble_occupied": self._ble_occupied,
            "last_activity": (
                self._last_activity.isoformat() if self._last_activity else None
            ),
            # v3.19.0: Face-confirmed arrival state
            "last_face_recognized": self._last_face_recognized,
            "last_face_time": self._last_face_time.isoformat() if self._last_face_time else None,
            "face_arrivals_today": self._face_arrivals_today,
        }


# ============================================================================
# State Inference Engine
# ============================================================================


class StateInferenceEngine:
    """Infer house state from Census, time, and occupancy signals.

    Rules (evaluated in priority order):
    1. Census shows 0 people + all zones away → AWAY
    2. Census shows people + sleep hours → SLEEP
    3. Unidentified persons detected while home → GUEST
    4. Census shows people + time-based variant → HOME_DAY/EVENING/NIGHT
    5. Census shows new arrivals from AWAY → ARRIVING
    """

    def __init__(
        self,
        sleep_start_hour: int = 23,
        sleep_end_hour: int = 6,
        evening_start_hour: int = 18,
        night_start_hour: int = 21,
    ) -> None:
        self.sleep_start_hour = sleep_start_hour
        self.sleep_end_hour = sleep_end_hour
        self.evening_start_hour = evening_start_hour
        self.night_start_hour = night_start_hour
        self._confidence: float = 0.0

    @property
    def confidence(self) -> float:
        """Return confidence of last inference."""
        return self._confidence

    def infer(
        self,
        census_count: int,
        current_state: HouseState,
        any_zone_occupied: bool,
        now: Optional[datetime] = None,
        unidentified_count: int = 0,
        guest_gate_armed: bool = False,
        all_tracked_persons_away: bool = False,
    ) -> Optional[HouseState]:
        """Infer the appropriate house state.

        Returns the inferred state, or None if no change is warranted.

        v4.6.2.2: guest_gate_armed replaces the raw unidentified_count > 0
        check for guest entry. It is pre-evaluated by PresenceCoordinator via
        _guest_gate_armed() which applies threshold, confidence, and persistence
        guards before passing the armed flag in.

        v4.7.14: all_tracked_persons_away is a person-tracker veto signal.
        When True (all configured person.* entities are not_home) AND there
        are no unidentified people in the house, return AWAY regardless of
        camera Tier 2 motion. Defends against camera ghost-presence.
        """
        if now is None:
            now = dt_util.now()

        hour = now.hour

        # Nobody home
        if census_count == 0 and not any_zone_occupied:
            if current_state == HouseState.AWAY:
                return None  # Already away
            self._confidence = 0.9
            return HouseState.AWAY

        # v4.7.14: Person-tracker veto — if all configured phone trackers say
        # away AND no unidentified person is in the house, return AWAY
        # regardless of camera Tier 2 motion. Defends against camera
        # ghost-presence (Frigate motion-without-person-ID on empty rooms).
        # Note: unidentified_count > 0 preserves guest detection — a guest at
        # the door triggering camera motion legitimately means someone IS here
        # even if all tracked persons are away.
        if all_tracked_persons_away and unidentified_count == 0:
            if current_state == HouseState.AWAY:
                return None  # Already away
            self._confidence = 0.95  # higher than camera-driven 0.85
            return HouseState.AWAY

        # People are home — determine variant
        has_people = census_count > 0 or any_zone_occupied

        if not has_people:
            return None

        # Arriving transition from AWAY
        if current_state == HouseState.AWAY:
            self._confidence = 0.85
            return HouseState.ARRIVING

        # Arriving → time-based home (must resolve before sleep/guest checks;
        # ARRIVING→SLEEP is not a valid state machine transition, so we first
        # move to HOME_*, then the next inference cycle handles HOME_*→SLEEP).
        if current_state == HouseState.ARRIVING:
            self._confidence = 0.85
            return self._time_based_home(hour)

        # Sleep hours (don't enter guest mode during sleep)
        if self._is_sleep_hour(hour):
            if current_state not in (HouseState.SLEEP, HouseState.WAKING):
                self._confidence = 0.7
                return HouseState.SLEEP
            return None

        # Waking transition
        if current_state == HouseState.SLEEP:
            self._confidence = 0.8
            return HouseState.WAKING

        # Waking → HOME_DAY
        if current_state == HouseState.WAKING:
            self._confidence = 0.85
            return HouseState.HOME_DAY

        # v3.15.0 / v4.6.2.2: Guest detection — unidentified persons while home.
        # v4.6.2.2: guest_gate_armed pre-applies threshold + confidence +
        # persistence guards (see PresenceCoordinator._guest_gate_armed).
        # NOTE: ARRIVING excluded — must transition to HOME_* first (GUEST is
        # not a valid transition from ARRIVING). Guest detection fires next cycle.
        if guest_gate_armed and current_state in (
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
        ):
            if current_state != HouseState.GUEST:
                self._confidence = 0.8
                return HouseState.GUEST
        # Guest mode exit — unidentified gone AND guest_room gate clear.
        # Exit is immediate (no persistence guard — cheaper to leave than to enter).
        # v4.7.2 D5: check guest_gate_armed (OR of both paths) not just unidentified_count
        # so the guest_room path can hold the state even with unidentified_count==0.
        if current_state == HouseState.GUEST and unidentified_count == 0 and not guest_gate_armed:
            self._confidence = 0.75
            return self._time_based_home(hour)

        # Time-based transitions while home
        time_home = self._time_based_home(hour)
        if current_state in (
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
        ):
            if time_home != current_state:
                self._confidence = 0.75
                return time_home
            return None

        return None

    def _time_based_home(self, hour: int) -> HouseState:
        """Determine HOME variant based on time of day.

        Timeline (with defaults): 0-5 night, 6-17 day, 18-20 evening, 21+ night.
        Hours before sleep_end (0-5 AM) are HOME_NIGHT so the valid
        transition HOME_NIGHT → SLEEP can fire on the next cycle.
        """
        if hour >= self.night_start_hour:
            return HouseState.HOME_NIGHT
        if hour >= self.evening_start_hour:
            return HouseState.HOME_EVENING
        if hour < self.sleep_end_hour:
            return HouseState.HOME_NIGHT
        return HouseState.HOME_DAY

    def _is_sleep_hour(self, hour: int) -> bool:
        """Check if current hour is within sleep hours."""
        if self.sleep_start_hour > self.sleep_end_hour:
            # Crosses midnight (e.g., 23-6)
            return hour >= self.sleep_start_hour or hour < self.sleep_end_hour
        return self.sleep_start_hour <= hour < self.sleep_end_hour


# ============================================================================
# Presence Coordinator
# ============================================================================


class PresenceCoordinator(BaseCoordinator):
    """Presence domain coordinator.

    Infers house state from Census + time + zone occupancy.
    Manages zone presence tracking with 3-tier signal support.
    Publishes SIGNAL_HOUSE_STATE_CHANGED.
    """

    PRESENCE_METRICS = [
        "census_count",
        "zone_occupied_count",
        "transition_count_daily",
    ]

    def __init__(
        self,
        hass: HomeAssistant,
        sleep_start_hour: int = 23,
        sleep_end_hour: int = 6,
        guest_persistence_seconds: int = 300,
        guest_require_confidence: str = "medium",
    ) -> None:
        super().__init__(
            hass=hass,
            coordinator_id="presence",
            name="Presence Coordinator",
            priority=60,
        )
        self._inference_engine = StateInferenceEngine(
            sleep_start_hour=sleep_start_hour,
            sleep_end_hour=sleep_end_hour,
        )
        self._zone_trackers: Dict[str, ZonePresenceTracker] = {}
        self._census_count: int = 0
        self._unidentified_count: int = 0
        # v4.7.14: Person-tracker veto diagnostics (populated by _run_inference).
        self._tracked_persons_count: int = 0
        self._all_tracked_persons_away: bool = False
        # v4.7.15 D1: Last shared-veto-helper decision (diagnostics).
        # Populated each _run_inference tick when the helper is consulted.
        self._last_veto_decision: VetoDecision = VetoDecision(False, 0.0, "", "")
        # v4.7.15 D3: Sustained-occupancy tracking — set when any_zone_occupied
        # flips False -> True, cleared when False. Drives WAKING gate.
        self._first_positive_zone_occupied_since: Optional[datetime] = None
        self._wake_blocked_ticks: int = 0
        # v4.7.15 D3: Exit-side persistence for GUEST -> HOME_*. Set when
        # the "no unidentified, no guest_gate_armed" condition first becomes
        # true while in GUEST state; cleared when it goes false.
        self._guest_exit_quiet_since: Optional[datetime] = None
        # v4.7.15 D5: Per-cycle signal_consensus + sustained-low tracker.
        self._signal_consensus: float = 1.0
        self._signal_consensus_inputs: Dict[str, Any] = {}
        self._consensus_low_since: Optional[datetime] = None
        self._transitions_today: int = 0
        self._transition_reset_date: str = ""
        # Room area_id lookup: room_name -> area_id (from config entries)
        self._room_area_ids: Dict[str, str] = {}
        # Deferred retry for hysteresis-blocked transitions
        self._retry_unsub: Optional[Any] = None
        # Outcome measurement
        self._outcome_true_positives: int = 0
        self._outcome_false_positives: int = 0
        self._last_transition_state: Optional[HouseState] = None
        self._last_transition_time: Optional[datetime] = None
        # Observation mode: when True, inference and zone tracking continue
        # but SIGNAL_HOUSE_STATE_CHANGED and SIGNAL_PERSON_ARRIVING are not
        # dispatched.  Controlled via switch.ura_presence_observation_mode.
        self.observation_mode: bool = False

        # v3.19.0: Face-confirmed arrival state
        self._face_arrival_cooldown: Dict[str, datetime] = {}
        self._face_recognition_enabled: bool = False
        # v3.21.0 D2: Ready event for downstream coordinators (e.g., HVAC).
        # Initialized as None here; created in async_setup() to ensure it
        # binds to the correct event loop (review fix F3).
        self._ready_event: asyncio.Event | None = None

        # v4.6.2.2: Guest mode false-positive hardening
        # Census confidence fields — updated by _handle_census_update
        self._census_confidence: str = "none"
        # Persistence arm: timestamp of first qualifying unidentified tick
        self._unidentified_first_seen: Optional[datetime] = None
        # Deferred recheck handle — cancelled on disarm, gate fire, and unload
        self._guest_persistence_check_handle: Optional[Any] = None
        # Guest mode config knobs
        self._guest_persistence_seconds: int = guest_persistence_seconds
        self._guest_require_confidence: str = guest_require_confidence

        # v4.7.2 D5: Sustained-occupancy guest signal (Feature B)
        # Per-room anti-flap state machine. Keyed by room_name.
        # {room_name: {"first_seen": Optional[datetime], "current_occupancy_known": bool}}
        self._guest_room_state: Dict[str, dict] = {}
        # Per-room listener unsubs (separate from _unsub_listeners for targeted cleanup)
        self._guest_room_unsubs: Dict[str, Any] = {}

    @property
    def inference_engine(self) -> StateInferenceEngine:
        """Return the state inference engine."""
        return self._inference_engine

    @property
    def zone_trackers(self) -> Dict[str, ZonePresenceTracker]:
        """Return zone presence trackers."""
        return self._zone_trackers

    @property
    def census_count(self) -> int:
        """Return current census count."""
        return self._census_count

    @property
    def house_state(self) -> str:
        """Return current house state from the manager's state machine."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "away"
        state = manager.house_state
        return state.value if hasattr(state, 'value') else str(state)

    @property
    def confidence(self) -> float:
        """Return confidence of current state inference."""
        return self._inference_engine.confidence

    # ------------------------------------------------------------------
    # v4.7.15 D1: Shared Bug Class #48 veto helper
    # ------------------------------------------------------------------
    def should_veto_due_to_reliable_signals(
        self,
        *,
        reliable_signals: List[ReliableSignal],
        transient_signals: List[TransientSignal],
        state_context: Dict[str, Any],
    ) -> VetoDecision:
        """Bug Class #48 arbitration: reliable-signal veto of transient evidence.

        v4.7.15 D1: Promotes the v4.7.13 (zone aggregator SLEEP) and v4.7.14
        (house inference AWAY) inline patterns to a shared utility so future
        cycles (v4.7.16 room-level, v4.8.x BLE proximity) plug new patterns
        here rather than fork the logic. Default fall-through is fired=False —
        adding a new caller without a matching pattern is a no-op.

        Patterns shipped (scope dispatch):
          - "house_inference"  : Pattern A — v4.7.14 AWAY veto
          - "zone_aggregator"  : Pattern B (SLEEP, v4.7.13) + Pattern C (non-sleep, v4.7.15 D2)
          - "waking_transition": Pattern D — v4.7.15 D3 sustained-signal WAKING gate
          - "guest_exit"       : Pattern E — v4.7.15 D3 GUEST→HOME exit-side persistence
        """
        scope = str(state_context.get("scope", ""))
        # Bug Class #22 mitigation: accept enum or string for house_state.
        _hs_raw = state_context.get("house_state", "")
        house_state = str(getattr(_hs_raw, "value", _hs_raw)).lower()
        tracked_count = int(state_context.get("tracked_count", 0))

        # Pattern A — v4.7.14 house-inference AWAY veto.
        if scope == "house_inference":
            all_away = any(
                s.kind == "person_tracker_away" and s.value for s in reliable_signals
            )
            any_home = any(
                s.kind == "person_tracker_home" and s.value for s in reliable_signals
            )
            unid = next(
                (s.count for s in transient_signals
                 if s.kind == "unidentified_person_count"),
                0,
            )
            if tracked_count > 0 and all_away and not any_home and unid == 0:
                return VetoDecision(
                    True, 0.95, "all_tracked_persons_away (no guests)", scope,
                )
            return VetoDecision(False, 0.0, "", scope)

        # Pattern B — v4.7.13 zone-aggregator SLEEP fallback.
        if scope == "zone_aggregator" and house_state == "sleep":
            any_home = any(
                s.kind == "zone_persons_home" and s.value for s in reliable_signals
            )
            if any_home:
                return VetoDecision(True, 0.90, "zone_persons home during sleep", scope)
            return VetoDecision(False, 0.0, "", scope)

        # Pattern C — v4.7.15 D2 zone-aggregator non-sleep states.
        if scope == "zone_aggregator" and house_state in (
            "home_day", "home_evening", "home_night",
            "arriving", "guest", "waking",
        ):
            any_home = any(
                s.kind == "zone_persons_home" and s.value for s in reliable_signals
            )
            sensors_quiet_seconds = int(
                state_context.get("room_sensors_quiet_seconds", 0)
            )
            if any_home and sensors_quiet_seconds >= _NONSLEEP_QUIET_THRESHOLD_SECONDS:
                return VetoDecision(
                    True,
                    0.85,
                    f"zone_persons home during {house_state} "
                    f"(quiet {sensors_quiet_seconds}s)",
                    scope,
                )
            return VetoDecision(False, 0.0, "", scope)

        # Pattern D — v4.7.15 D3 WAKING sustained-signal gate.
        if scope == "waking_transition":
            sustained_seconds = int(
                state_context.get("sustained_occupancy_seconds", 0)
            )
            if sustained_seconds >= _WAKING_SUSTAINED_THRESHOLD_SECONDS:
                return VetoDecision(
                    False, 0.85,
                    f"sustained occupancy confirms wake ({sustained_seconds}s)",
                    scope,
                )
            return VetoDecision(
                True, 0.6,
                f"insufficient sustained signal ({sustained_seconds}s "
                f"< {_WAKING_SUSTAINED_THRESHOLD_SECONDS}s)",
                scope,
            )

        # Pattern E — v4.7.15 D3 GUEST exit-side persistence.
        if scope == "guest_exit":
            quiet_seconds = int(state_context.get("guest_exit_quiet_seconds", 0))
            threshold = int(
                state_context.get(
                    "guest_persistence_seconds", self._guest_persistence_seconds,
                )
            )
            if threshold <= 0:
                return VetoDecision(False, 0.0, "guest exit persistence disabled", scope)
            if quiet_seconds >= threshold:
                return VetoDecision(
                    False, 0.85,
                    f"guest exit sustained ({quiet_seconds}s >= {threshold}s)",
                    scope,
                )
            return VetoDecision(
                True, 0.7,
                f"guest exit not yet sustained ({quiet_seconds}s < {threshold}s)",
                scope,
            )

        # Unknown / unmatched scope — fall through (forward compatible).
        return VetoDecision(False, 0.0, "", scope)

    # ------------------------------------------------------------------
    # v4.7.15 D4: Multi-source zone occupancy confidence (relocated from HVAC)
    # ------------------------------------------------------------------
    def check_zone_occupancy_confidence(self, zone) -> tuple[int, int]:
        """Count independent occupancy sources confirming zone presence.

        Migrated from hvac.py:1350 in v4.7.15 D4. Identical semantics; now
        public on PresenceCoordinator so D5/D6 consensus calc and v4.7.16
        room-level callers can consume it without HVAC ↔ presence circular
        imports.

        Returns (confirmed, possible) where:
        - confirmed: number of source types actively confirming presence (0-4)
        - possible: number of source types available for this zone (0-4)

        Source types:
        1. Motion/mmWave sensors (recent activity within 30 min)
        2. BLE person detection (phone detected in zone)
        3. Camera person detection (Frigate person entity "on")
        4. Multiple occupied rooms (2+ rooms occupied = unlikely all stuck)

        The caller uses adaptive threshold: require min(2, possible) sources.
        Accepts HVAC's `Zone` dataclass shape duck-typed (reads .rooms,
        .zone_cameras, .room_conditions).
        """
        # function-local import — Bug Class #34
        from ..const import (  # noqa: PLC0415
            CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM,
        )
        confirmed = 0
        possible = 0

        # Source 1: Motion/mmWave — always available (every room has sensors)
        possible += 1
        has_recent_motion = False
        now = dt_util.utcnow()
        try:
            for room_name in getattr(zone, "rooms", []) or []:
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if (
                        entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
                        and entry.data.get(CONF_ROOM_NAME) == room_name
                    ):
                        coord = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
                        if (
                            coord
                            and hasattr(coord, "_last_motion_time")
                            and coord._last_motion_time
                        ):
                            age = (now - coord._last_motion_time).total_seconds()
                            if age < 1800:  # Motion in last 30 min
                                has_recent_motion = True
                        break
        except Exception:  # noqa: BLE001 — defensive: stale registry
            pass
        if has_recent_motion:
            confirmed += 1

        # Source 2: BLE person detection
        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if person_coord:
            possible += 1
            try:
                ble_persons = person_coord.get_persons_in_zone(
                    getattr(zone, "rooms", []) or [],
                )
                if ble_persons:
                    confirmed += 1
            except Exception:  # noqa: BLE001
                pass

        # Source 3: Camera person detection
        zone_cameras = getattr(zone, "zone_cameras", None) or []
        if zone_cameras:
            possible += 1
            for camera_entity in zone_cameras:
                state = self.hass.states.get(camera_entity)
                if state and state.state == "on":
                    confirmed += 1
                    break  # One camera confirmation is enough

        # Source 4: Multiple occupied rooms (only possible if zone has 2+ rooms)
        rooms = getattr(zone, "rooms", []) or []
        if len(rooms) >= 2:
            possible += 1
            try:
                room_conditions = getattr(zone, "room_conditions", []) or []
                occupied_count = sum(
                    1 for rc in room_conditions if getattr(rc, "occupied", False)
                )
                if occupied_count >= 2:
                    confirmed += 1
            except Exception:  # noqa: BLE001
                pass

        return confirmed, possible

    def get_next_state_prediction(self) -> dict:
        """Return the next-state prediction in the D1 PWA contract shape.

        v4.6.9 D1: No predictive model exists yet — this is a placeholder.
        The routine awareness v4.6.0 cycle introduced regime shift *detection*
        (RegimeDetector, nightly batch) but not forward next-state prediction.
        A real model (e.g. time-of-day Bayesian transition forecaster) is
        planned for v4.7.x.

        Until then we emit:
          state       = "unknown"
          confidence  = 0.0
          model       = "placeholder_v0"

        This satisfies the PWA hook contract (no "—"/None as state value)
        while making the gap explicit.  The TODO below is the v4.7.x hook-in.

        TODO(v4.7.x): Replace this stub with a real model call, e.g.:
          forecaster = self.hass.data[DOMAIN].get("routine_forecaster")
          if forecaster is not None:
              return forecaster.get_next_state_prediction()
        """
        # function-local import — Bug Class #34
        try:
            from homeassistant.util import dt as _dt_util
            predicted_at_iso = _dt_util.utcnow().isoformat()
        except Exception:
            from datetime import datetime, timezone
            predicted_at_iso = datetime.now(timezone.utc).isoformat()

        current_state = self.house_state

        return {
            "state": "unknown",
            "confidence": 0.0,
            "predicted_at_iso": predicted_at_iso,
            "model": "placeholder_v0",
            "current_state": current_state,
            "transition_eta_minutes": None,
        }

    async def async_setup(self) -> None:
        """Set up the Presence Coordinator.

        Discovers zones and their rooms, sets up zone trackers,
        subscribes to Census and occupancy signals, discovers zone cameras.
        """
        import asyncio
        # v3.21.0 D2: Create ready event on the event loop (not in __init__)
        self._ready_event = asyncio.Event()

        _LOGGER.info("Setting up Presence Coordinator")

        # v3.6.0.3: Instantiate anomaly detector FIRST so it's always available
        # even if discovery fails. Minimum 24 samples (~1 day of hourly
        # observations) before activation.
        # v4.6.3 D10: sensitivity bucket from CM entry options.
        from .coordinator_diagnostics import AnomalyDetector
        from ..const import (  # noqa: PLC0415
            CONF_PRESENCE_ANOMALY_SENSITIVITY,
            DEFAULT_ANOMALY_SENSITIVITY,
            ANOMALY_SENSITIVITY_MULTIPLIERS,
            ENTRY_TYPE_COORDINATOR_MANAGER,
        )
        _presence_sensitivity = DEFAULT_ANOMALY_SENSITIVITY
        try:
            for _ce in self.hass.config_entries.async_entries(DOMAIN):
                if _ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    _presence_sensitivity = {**_ce.data, **_ce.options}.get(
                        CONF_PRESENCE_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                    )
                    break
        except Exception:
            pass
        self.anomaly_detector = AnomalyDetector(
            hass=self.hass,
            coordinator_id="presence",
            metric_names=self.PRESENCE_METRICS,
            minimum_samples=24,
            sensitivity_multiplier=ANOMALY_SENSITIVITY_MULTIPLIERS.get(_presence_sensitivity, 1.0),
            # v4.6.5.3 surface fix: census_count + zone_occupied_count fire
            # in-memory (degenerate-shape per v4.6.3.1 / v4.6.3.3 doctrine) but
            # are suppressed from persistence — exclude them from the sensor's
            # severity calculation so it doesn't permanently show critical.
            suppressed_metric_names=PRESENCE_SUPPRESSED_FROM_PERSISTENCE,
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception:
            _LOGGER.debug("Could not load presence anomaly baselines (non-fatal)", exc_info=True)

        # v4.6.5.1 P4 (M3 fix from v4.6.4 review): hydrate _transitions_today
        # from house_state_log so the daily counter survives reload/restart.
        # Without this, the counter resets to 0 on every restart and the
        # transition_count_daily baseline distribution skews low —
        # biasing future thrashy-day anomalies to fire more than they should.
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None:
                today_iso = dt_util.now().date().isoformat()
                count = await db.count_house_state_changes_since(today_iso)
                self._transitions_today = count
                self._transition_reset_date = today_iso
                _LOGGER.info(
                    "Hydrated _transitions_today=%d from house_state_log (since %s)",
                    count, today_iso,
                )
        except Exception:
            _LOGGER.debug(
                "Could not hydrate _transitions_today from house_state_log (non-fatal)",
                exc_info=True,
            )

        # v3.19.0: Read face recognition toggle from integration config
        try:
            from ..const import CONF_FACE_RECOGNITION_ENABLED, ENTRY_TYPE_INTEGRATION, CONF_ENTRY_TYPE
            for config_entry in self.hass.config_entries.async_entries(DOMAIN):
                if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                    merged = {**config_entry.data, **config_entry.options}
                    self._face_recognition_enabled = merged.get(CONF_FACE_RECOGNITION_ENABLED, False)
                    break
        except Exception:
            self._face_recognition_enabled = False

        # v3.6.0.3: Wrap discovery/subscription in try/except so partial
        # failures don't prevent the coordinator from functioning.
        try:
            # Build room → area_id mapping from room config entries
            self._build_room_area_map()

            # Discover zones and create trackers
            self._discover_zones()

            # Discover and subscribe to room occupancy sensors (Tier 1)
            self._discover_room_sensors()

            # Discover and subscribe to zone cameras (Tier 2)
            self._discover_zone_cameras()

            # v4.7.2 D5: Discover and subscribe to guest rooms (Feature B)
            self._discover_guest_rooms()

            # Subscribe to geofence (person entity state changes)
            self._subscribe_geofence()

            # Subscribe to census updates
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            self._unsub_listeners.append(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_CENSUS_UPDATED,
                    self._handle_census_update,
                )
            )

            # Periodic inference (every 60 seconds for time-based transitions + camera timeouts)
            self._unsub_listeners.append(
                async_track_time_interval(
                    self.hass,
                    self._periodic_inference,
                    timedelta(seconds=60),
                )
            )
        except Exception:
            _LOGGER.exception("Error during presence discovery (non-fatal)")

        # v3.6.0-c2.3: Seed census count from existing data before first
        # inference. Without this, _census_count=0 → infers "away" even
        # when people are home. Read from census manager if available,
        # else fall back to the identified_persons sensor state.
        try:
            census_mgr = self.hass.data.get(DOMAIN, {}).get(
                "camera_integration_manager"
            )
            if census_mgr and hasattr(census_mgr, "last_result"):
                last = census_mgr.last_result
                if last is not None:
                    self._census_count = last.house.total_persons
                    _LOGGER.info(
                        "Seeded census count from manager: %d",
                        self._census_count,
                    )
            if self._census_count == 0:
                # Fallback: read from sensor state
                state = self.hass.states.get(
                    f"sensor.{DOMAIN}_identified_persons_in_house"
                )
                if state and state.state not in ("unknown", "unavailable"):
                    try:
                        self._census_count = int(state.state)
                        _LOGGER.info(
                            "Seeded census count from sensor: %d",
                            self._census_count,
                        )
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            _LOGGER.warning("Failed to seed census count: %s", e)

        # Run initial inference with seeded census count
        await self._run_inference("startup")

        # v3.21.0 D2: Signal readiness so downstream coordinators (HVAC) can
        # safely read house state without racing startup ordering.
        self._ready_event.set()

        _LOGGER.info(
            "Presence Coordinator ready: %d zones tracked",
            len(self._zone_trackers),
        )

    def _build_room_area_map(self) -> None:
        """Build room_name → area_id mapping from room config entries.

        v3.6.0.11: Falls back to matching room names against HA area registry
        names when CONF_AREA_ID is not configured on the room entry.
        """
        from ..const import CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM

        # Build name→area_id lookup from HA area registry for fallback
        area_name_to_id: Dict[str, str] = {}
        try:
            from homeassistant.helpers import area_registry as ar
            area_reg = ar.async_get(self.hass)
            for area in area_reg.async_list_areas():
                area_name_to_id[area.name.lower()] = area.area_id
        except Exception:
            _LOGGER.debug("Cannot access area registry for room area fallback")

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                room_name = entry.data.get(CONF_ROOM_NAME, "")
                area_id = (
                    entry.options.get(CONF_AREA_ID)
                    or entry.data.get(CONF_AREA_ID)
                )
                # Fallback: match room name to HA area name
                if not area_id and room_name:
                    area_id = area_name_to_id.get(room_name.lower())
                    if area_id:
                        _LOGGER.debug(
                            "Room '%s' area_id resolved via area registry: %s",
                            room_name, area_id,
                        )
                if room_name and area_id:
                    self._room_area_ids[room_name] = area_id

        _LOGGER.info(
            "Room area map: %d rooms mapped to areas: %s",
            len(self._room_area_ids),
            {k: v for k, v in self._room_area_ids.items()},
        )

    def _discover_zones(self) -> None:
        """Discover zones and their rooms from config entries.

        v3.6.0.2: Full diagnostic logging + entry ID resolution.
        """
        from ..const import (
            CONF_ENTRY_TYPE, ENTRY_TYPE_ZONE, ENTRY_TYPE_ZONE_MANAGER,
            CONF_ZONE_NAME, CONF_ROOM_NAME,
        )

        all_entries = self.hass.config_entries.async_entries(DOMAIN)
        entry_types = [e.data.get(CONF_ENTRY_TYPE, "unknown") for e in all_entries]
        _LOGGER.info(
            "Zone discovery: %d config entries, types: %s",
            len(all_entries), entry_types,
        )

        # Legacy: individual ENTRY_TYPE_ZONE entries
        for entry in all_entries:
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                zone_name = entry.data.get(CONF_ZONE_NAME, "")
                room_names = list(
                    entry.options.get(CONF_ZONE_ROOMS, [])
                    or entry.data.get(CONF_ZONE_ROOMS, [])
                )
                if zone_name and room_names:
                    self._zone_trackers[zone_name] = ZonePresenceTracker(
                        hass=self.hass,
                        zone_name=zone_name,
                        room_names=room_names,
                    )
                    _LOGGER.info(
                        "Zone tracker created (legacy): %s with rooms %s",
                        zone_name, room_names,
                    )

        # Zone Manager entry: zones in data["zones"] or options["zones"]
        zm_found = False
        for entry in all_entries:
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                zm_found = True
                # Check both data and options for zones
                data_zones = entry.data.get("zones", {})
                opts_zones = entry.options.get("zones", {})
                _LOGGER.info(
                    "Zone Manager found: entry_id=%s, data has %d zones, options has %d zones, "
                    "data keys: %s, options keys: %s",
                    entry.entry_id,
                    len(data_zones), len(opts_zones),
                    list(data_zones.keys()) if data_zones else "[]",
                    list(opts_zones.keys()) if opts_zones else "[]",
                )

                # Options takes priority over data (config flow writes to options)
                zones_data = opts_zones if opts_zones else data_zones

                for zone_name, zone_cfg in zones_data.items():
                    if zone_name in self._zone_trackers:
                        continue
                    raw_rooms = list(zone_cfg.get(CONF_ZONE_ROOMS, []))
                    _LOGGER.info(
                        "Zone '%s' raw room refs: %s", zone_name, raw_rooms,
                    )
                    # Resolve entry IDs to room names
                    room_names = []
                    for room_ref in raw_rooms:
                        room_entry = self.hass.config_entries.async_get_entry(room_ref)
                        if room_entry:
                            name = room_entry.data.get(CONF_ROOM_NAME, "")
                            if name:
                                room_names.append(name)
                                _LOGGER.debug(
                                    "  Resolved %s -> '%s'", room_ref[:12], name,
                                )
                                continue
                        # Fallback: treat as a room name directly
                        room_names.append(room_ref)
                        _LOGGER.debug(
                            "  Fallback (no entry): %s used as-is", room_ref[:20],
                        )
                    if zone_name and room_names:
                        self._zone_trackers[zone_name] = ZonePresenceTracker(
                            hass=self.hass,
                            zone_name=zone_name,
                            room_names=room_names,
                        )
                        _LOGGER.info(
                            "Zone tracker created: '%s' with %d rooms: %s",
                            zone_name, len(room_names), room_names,
                        )
                    else:
                        _LOGGER.warning(
                            "Zone '%s' skipped: zone_name=%r, room_names=%s",
                            zone_name, zone_name, room_names,
                        )
                break

        if not zm_found:
            _LOGGER.warning("No Zone Manager entry found among %d entries", len(all_entries))

        _LOGGER.info(
            "Zone discovery complete: %d zone trackers created: %s",
            len(self._zone_trackers), list(self._zone_trackers.keys()),
        )

    # ------------------------------------------------------------------
    # Tier 1: Room Occupancy Sensors (via entity registry area_id)
    # ------------------------------------------------------------------

    def _discover_room_sensors(self) -> None:
        """Discover room occupancy sensors using entity/device registry area_id.

        v3.6.0.11: Also checks device area_id when entity area_id is null.
        Many Zigbee/MQTT sensors have area_id on the device, not the entity.
        """
        try:
            from homeassistant.helpers import entity_registry as er
            from homeassistant.helpers import device_registry as dr
            ent_reg = er.async_get(self.hass)
            dev_reg = dr.async_get(self.hass)
        except Exception:
            _LOGGER.warning("Cannot access entity/device registry — room sensor discovery skipped")
            return

        entity_ids: Set[str] = set()
        occupancy_keywords = ("occupancy", "motion", "presence", "mmwave")

        for _zone_name, tracker in self._zone_trackers.items():
            for room_name in tracker.room_names:
                area_id = self._room_area_ids.get(room_name)
                if not area_id:
                    _LOGGER.debug(
                        "Room '%s' has no area_id configured — trying name-based fallback",
                        room_name,
                    )
                    self._discover_room_sensors_by_name(
                        tracker, room_name, entity_ids,
                    )
                    continue

                # Find binary_sensor entities assigned to this area
                # Check both entity area_id and device area_id (fallback)
                for entity in ent_reg.entities.values():
                    if entity.domain != "binary_sensor":
                        continue
                    if not any(kw in entity.entity_id for kw in occupancy_keywords):
                        continue

                    # Resolve effective area: entity → device fallback
                    effective_area = entity.area_id
                    if not effective_area and entity.device_id:
                        dev_entry = dev_reg.async_get(entity.device_id)
                        if dev_entry:
                            effective_area = dev_entry.area_id

                    if effective_area == area_id:
                        entity_ids.add(entity.entity_id)
                        tracker.register_entity(entity.entity_id, room_name)
                        _LOGGER.debug(
                            "Zone %s: room %s (area %s) → occupancy sensor %s",
                            _zone_name, room_name, area_id, entity.entity_id,
                        )

        if entity_ids:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    list(entity_ids),
                    self._handle_occupancy_change,
                )
            )
            _LOGGER.info(
                "Subscribed to %d room occupancy entities across %d zones",
                len(entity_ids), len(self._zone_trackers),
            )

    def _discover_room_sensors_by_name(
        self,
        tracker: ZonePresenceTracker,
        room_name: str,
        entity_ids: Set[str],
    ) -> None:
        """Fallback: discover occupancy sensors by name matching.

        Only used when a room has no area_id configured. Less reliable
        than area_id-based discovery — a room named "den" could match
        "garden_motion", so we require BOTH the room name AND an occupancy
        keyword in the entity_id.
        """
        room_lower = room_name.lower().replace(" ", "_")
        occupancy_keywords = ("occupancy", "motion", "presence", "mmwave")

        # Avoid matching short room names that are substrings of unrelated entities
        if len(room_lower) < 3:
            _LOGGER.warning(
                "Room name '%s' is too short for name-based sensor matching — skipping",
                room_name,
            )
            return

        for state in self.hass.states.async_all():
            entity_id = state.entity_id
            if not entity_id.startswith("binary_sensor."):
                continue

            # Require BOTH room name and occupancy keyword
            entity_suffix = entity_id[len("binary_sensor."):]
            if (
                room_lower in entity_suffix
                and any(kw in entity_suffix for kw in occupancy_keywords)
            ):
                entity_ids.add(entity_id)
                tracker.register_entity(entity_id, room_name)
                _LOGGER.debug(
                    "Zone %s: room %s → occupancy sensor %s (name-based fallback)",
                    tracker.zone_name, room_name, entity_id,
                )

    # ------------------------------------------------------------------
    # Tier 2: Zone Camera Sensors (via CameraIntegrationManager)
    # ------------------------------------------------------------------

    def _discover_zone_cameras(self) -> None:
        """Discover cameras in each zone using CameraIntegrationManager.

        Cameras are mapped to zones via their area_id in the entity registry.
        If a camera's area_id matches a room's area_id, and that room is in
        a zone, the camera's person detection entity is subscribed for that zone.

        This mirrors how camera_census.py uses area_id for camera→room mapping,
        but applied at the zone level.
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            _LOGGER.debug("No coordinator manager — camera discovery skipped")
            return

        # Get CameraIntegrationManager from the coordinator data
        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        if camera_manager is None:
            _LOGGER.debug("No camera manager initialized — zone camera discovery skipped")
            return

        if not camera_manager.has_cameras():
            _LOGGER.debug("No cameras discovered — zone camera signals unavailable")
            return

        camera_entity_ids: Set[str] = set()

        # Build area_id → zone mapping from room → zone assignments
        area_to_zone: Dict[str, str] = {}
        for zone_name, tracker in self._zone_trackers.items():
            for room_name in tracker.room_names:
                area_id = self._room_area_ids.get(room_name)
                if area_id:
                    area_to_zone[area_id] = zone_name

        # Find cameras in each zone's areas
        for area_id, zone_name in area_to_zone.items():
            cameras_in_area = camera_manager.get_cameras_for_area(area_id)
            tracker = self._zone_trackers[zone_name]

            for camera_info in cameras_in_area:
                person_sensor = camera_info.person_binary_sensor
                if person_sensor and person_sensor not in camera_entity_ids:
                    camera_entity_ids.add(person_sensor)
                    tracker.register_camera(person_sensor)
                    _LOGGER.debug(
                        "Zone %s: camera sensor %s (area %s, platform %s)",
                        zone_name, person_sensor, area_id, camera_info.platform,
                    )

        if camera_entity_ids:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    list(camera_entity_ids),
                    self._handle_camera_change,
                )
            )
            _LOGGER.info(
                "Subscribed to %d zone camera entities across %d zones",
                len(camera_entity_ids), len(self._zone_trackers),
            )

    # ------------------------------------------------------------------
    # Geofence: person entity state changes (home/not_home)
    # ------------------------------------------------------------------

    def _subscribe_geofence(self) -> None:
        """Subscribe to person.* entity state changes for geofence signals.

        HA person entities track home/not_home/zone state. When a person
        transitions to 'home' from 'not_home' (or vice versa), this provides
        an early AWAY→ARRIVING signal before camera census updates.
        """
        person_entity_ids = [
            state.entity_id
            for state in self.hass.states.async_all()
            if state.entity_id.startswith("person.")
        ]

        if not person_entity_ids:
            _LOGGER.debug("No person entities found — geofence signal unavailable")
            return

        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass,
                person_entity_ids,
                self._handle_geofence_change,
            )
        )
        _LOGGER.info(
            "Subscribed to %d person entities for geofence signals",
            len(person_entity_ids),
        )

    @callback
    def _handle_geofence_change(self, event: Any) -> None:
        """Handle person entity state change (geofence transition)."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        new_zone = new_state.state
        old_zone = old_state.state if old_state else None

        # Guard: skip unavailable/unknown
        if new_zone in _UNAVAILABLE_STATES:
            return

        # Detect home arrival or departure
        if new_zone == "home" and old_zone != "home":
            self.handle_geofence_event(entity_id, "home")
            # v3.17.0 D3: Signal person arriving for HVAC zone pre-conditioning
            # v3.21.1 D1: Gate signal dispatch on observation mode
            if self.observation_mode:
                _LOGGER.info(
                    "[observation mode] Presence would dispatch "
                    "SIGNAL_PERSON_ARRIVING for %s (geofence) — suppressed",
                    entity_id,
                )
            else:
                from homeassistant.helpers.dispatcher import (
                    async_dispatcher_send as _dispatcher_send,
                )
                _dispatcher_send(
                    self.hass,
                    SIGNAL_PERSON_ARRIVING,
                    {"person_entity": entity_id, "source": "geofence"},
                )
        elif new_zone == "not_home" and old_zone == "home":
            self.handle_geofence_event(entity_id, "not_home")

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    @callback
    def _handle_census_update(self, census_data: dict) -> None:
        """Handle Census update signal."""
        old_count = self._census_count
        old_unidentified = self._unidentified_count
        # v4.6.2.3: Capture confidence BEFORE reassignment so the change-detection
        # comparison below is valid. Without this, comparing self._census_confidence
        # to self._census_confidence after the update would always be equal.
        old_confidence = self._census_confidence
        try:
            self._census_count = int(census_data.get("interior_count", 0))
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid census interior_count: %s — keeping previous value",
                census_data.get("interior_count"),
            )
            return

        # v3.15.0: Track unidentified count for guest mode
        try:
            self._unidentified_count = int(census_data.get("unidentified_count", 0))
        except (ValueError, TypeError):
            self._unidentified_count = 0

        # v4.6.2.2: Read confidence fields for guest gate — default to "none"
        # if not present (backward compat with any caller not yet sending them).
        try:
            self._census_confidence = str(
                census_data.get("confidence", "none") or "none"
            )
        except (TypeError, ValueError, KeyError, AttributeError):
            # Tolerate malformed signal payload (legacy subscribers or test stubs).
            _LOGGER.debug("Malformed census payload: could not read confidence field")
            self._census_confidence = "none"

        _LOGGER.debug(
            "Census update: count=%d unidentified=%d confidence=%s",
            self._census_count, self._unidentified_count, self._census_confidence,
        )

        # v4.6.2.3: Also trigger inference on confidence-only changes (e.g., low→high
        # with counts unchanged). Without this, a confidence upgrade waits up to the
        # next 60s periodic tick before the guest gate re-evaluates.
        if (
            old_count != self._census_count
            or old_unidentified != self._unidentified_count
            or old_confidence != self._census_confidence
        ):
            self.hass.async_create_task(self._run_inference("census_update"))

    @callback
    def _handle_occupancy_change(self, event: Any) -> None:
        """Handle room occupancy sensor state change.

        Guards against unavailable/unknown states — treats them as 'not occupied'
        to avoid false positives from offline sensors (lesson from camera_census).
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # Guard: treat unavailable/unknown as not occupied
        if new_state.state in _UNAVAILABLE_STATES:
            _LOGGER.debug(
                "Occupancy sensor %s is %s — treating as not occupied",
                entity_id, new_state.state,
            )
            occupied = False
        else:
            occupied = new_state.state == "on"

        # Find which zone and room this entity belongs to (via registered mapping)
        matched = False
        for _zone_name, tracker in self._zone_trackers.items():
            room_name = tracker._entity_to_room.get(entity_id)
            if room_name:
                tracker.update_room_occupancy(room_name, occupied)
                matched = True
                break

        if not matched:
            # Fallback: name-based matching for entities discovered by name
            for _zone_name, tracker in self._zone_trackers.items():
                for room_name in tracker.room_names:
                    room_lower = room_name.lower().replace(" ", "_")
                    if room_lower in entity_id:
                        tracker.update_room_occupancy(room_name, occupied)
                        matched = True
                        break
                if matched:
                    break

        self.hass.async_create_task(self._run_inference("occupancy_change"))

    @callback
    def _handle_camera_change(self, event: Any) -> None:
        """Handle camera person/motion detection state change.

        Guards against unavailable/unknown states. Camera detection uses
        timeout-based occupancy — when person is detected the zone stays
        occupied for _CAMERA_OCCUPANCY_TIMEOUT_SECONDS after detection ends.
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # Guard: unavailable/unknown means not detecting
        if new_state.state in _UNAVAILABLE_STATES:
            _LOGGER.debug(
                "Camera sensor %s is %s — treating as no detection",
                entity_id, new_state.state,
            )
            detected = False
        else:
            detected = new_state.state == "on"

        # Route to the correct zone tracker (EXISTING — unchanged)
        matched_zone_name = None
        for _zone_name, tracker in self._zone_trackers.items():
            if entity_id in tracker._camera_entity_ids:
                tracker.update_camera_detection(entity_id, detected)
                matched_zone_name = _zone_name
                break

        # v3.19.0: Face-confirmed arrival (ADDITIVE — all failures return gracefully)
        if detected and matched_zone_name and self._face_recognition_enabled:
            face_name = self._get_face_for_camera(entity_id)
            if face_name:
                self._handle_face_arrival(entity_id, face_name, matched_zone_name)

        self.hass.async_create_task(self._run_inference("camera_detection"))

    # ------------------------------------------------------------------
    # v3.19.0: Face-confirmed arrival helpers (additive — never modify
    # existing camera detection behavior, all failures return gracefully)
    # ------------------------------------------------------------------

    def _get_face_for_camera(self, camera_entity: str) -> Optional[str]:
        """Get recognized face from Frigate face sensor for this camera.

        v3.19.0: Uses confirmed Frigate naming pattern:
        binary_sensor.{name}_person_occupancy → sensor.{name}_last_recognized_face

        Returns face name if fresh (<30s), None on any failure.
        All failures are graceful — face rec is an accelerator, not a requirement.
        """
        try:
            # Derive face sensor from camera entity using Frigate naming convention
            bs_id = camera_entity
            base_name = None
            for suffix in ("_person_occupancy", "_person_detected", "_occupancy"):
                if bs_id.startswith("binary_sensor.") and bs_id.endswith(suffix):
                    base_name = bs_id[len("binary_sensor."):-len(suffix)]
                    break

            if not base_name:
                return None  # Not a recognized camera pattern

            face_sensor_id = f"sensor.{base_name}_last_recognized_face"
            state = self.hass.states.get(face_sensor_id)
            if not state:
                return None  # Face sensor doesn't exist

            # Check for valid face name
            face_value = state.state.strip() if state.state else ""
            if not face_value or face_value.lower() in ("unknown", "unavailable", "none", "no_match", ""):
                return None  # No face recognized

            # Freshness check: face rec must be recent (<30s)
            if state.last_changed:
                age = (dt_util.utcnow() - state.last_changed).total_seconds()
                if age > 30:  # FACE_FRESHNESS_SECONDS
                    return None  # Stale face data

            return face_value
        except Exception:  # noqa: BLE001
            return None  # Face rec is an accelerator — never fail

    @callback
    def _handle_face_arrival(self, camera_entity: str, face_name: str, zone_name: str) -> None:
        """Fire pre-arrival signal for face-recognized person in a zone.

        v3.19.0: Debounced (60s per person+zone). All failures graceful.
        """
        try:
            from homeassistant.helpers.dispatcher import async_dispatcher_send

            # Map face name to person entity
            person_entity = self._find_person_entity_from_face(face_name)
            if not person_entity:
                _LOGGER.debug("Face '%s' has no matching person entity — skipping", face_name)
                return

            # Debounce: 60s cooldown per person+zone
            key = f"{person_entity}:{zone_name}"
            now = dt_util.utcnow()
            last = self._face_arrival_cooldown.get(key)
            if last and (now - last).total_seconds() < 60:
                return
            self._face_arrival_cooldown[key] = now

            # Update zone tracker face state
            tracker = self._zone_trackers.get(zone_name)
            if tracker:
                tracker._last_face_recognized = face_name
                tracker._last_face_time = now
                tracker._face_arrivals_today += 1

            # Update HVAC zone counter if available
            try:
                manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                if manager:
                    hvac = manager.coordinators.get("hvac")
                    if hvac and hvac.zone_manager:
                        for _zid, zstate in hvac.zone_manager.zones.items():
                            if zstate.zone_name == zone_name:
                                zstate.camera_face_arrivals_today += 1
                                break
            except Exception:  # noqa: BLE001
                pass  # Best effort — don't fail face arrival on HVAC counter update

            # Fire the signal
            # v3.21.1 D1: Gate signal dispatch on observation mode
            if self.observation_mode:
                _LOGGER.info(
                    "[observation mode] Presence would dispatch "
                    "SIGNAL_PERSON_ARRIVING for %s (camera_face) in zone %s — suppressed",
                    face_name, zone_name,
                )
            else:
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_PERSON_ARRIVING,
                    {"person_entity": person_entity, "source": "camera_face"},
                )
                _LOGGER.info(
                    "Camera face arrival: %s recognized in zone %s via %s",
                    face_name, zone_name, camera_entity,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Face arrival handling failed (non-fatal)", exc_info=True)

    def _find_person_entity_from_face(self, face_name: str) -> Optional[str]:
        """Map Frigate face name to HA person entity.

        v3.19.0: Frigate face names are configured names (e.g., "Oji", "Jaya").
        Try matching to person.{lowercase_name}.
        """
        try:
            candidate = f"person.{face_name.lower().replace(' ', '_')}"
            if self.hass.states.get(candidate):
                return candidate
            # Try without modification
            candidate2 = f"person.{face_name}"
            if self.hass.states.get(candidate2):
                return candidate2
            return None
        except Exception:  # noqa: BLE001
            return None  # Face rec is an accelerator — never fail

    async def _periodic_inference(self, _now: Any = None) -> None:
        """Run periodic inference for time-based transitions and camera timeouts.

        Also updates BLE-based zone presence (Tier 3) from person_coordinator.
        """
        # Update BLE presence for each zone (Tier 3)
        self._update_ble_zone_presence()

        await self._run_inference("periodic")

    def _update_ble_zone_presence(self) -> None:
        """Update BLE-based zone presence from person_coordinator.

        Checks person_coordinator for persons located in rooms that belong
        to each zone. If any person is in a room within a zone, that zone
        is BLE-occupied.
        """
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator or not hasattr(person_coordinator, "data") or not person_coordinator.data:
            return

        for _zone_name, tracker in self._zone_trackers.items():
            zone_has_person = False
            for _person_id, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location and location not in ("away", "unknown", ""):
                    # Check if this person's room is in this zone
                    if location in tracker.room_names:
                        zone_has_person = True
                        break

            tracker.update_ble_presence(zone_has_person)

    def _schedule_deferred_retry(self, delay_seconds: float) -> None:
        """Schedule a one-shot deferred inference retry after hysteresis expires.

        v3.6.0.11: Prevents lost transitions when hysteresis blocks.
        """
        from homeassistant.helpers.event import async_call_later

        # Cancel any existing retry
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

        @callback
        def _retry_callback(_now):
            self._retry_unsub = None
            self.hass.async_create_task(self._run_inference("deferred_retry"))

        self._retry_unsub = async_call_later(
            self.hass, delay_seconds, _retry_callback,
        )
        _LOGGER.debug(
            "Deferred retry scheduled in %.0fs", delay_seconds,
        )

    # ------------------------------------------------------------------
    # v4.6.2.2: Guest mode hardening helpers
    # ------------------------------------------------------------------

    # Confidence level rank map — strict ordering for gate compare.
    # NEVER compare confidence strings lexicographically.
    _CONFIDENCE_RANK: dict = {"none": 0, "low": 1, "medium": 2, "high": 3}

    def _confidence_at_least(self, observed: str, required: str) -> bool:
        """Return True iff observed census confidence >= required level.

        Uses the private rank map to avoid lexicographic comparison bugs.
        Unknown values are treated as 'none' (rank 0) — safest default.
        """
        observed_rank = self._CONFIDENCE_RANK.get(observed, 0)
        required_rank = self._CONFIDENCE_RANK.get(required, 0)
        return observed_rank >= required_rank

    def _disarm_guest_gate(self) -> None:
        """Clear all guest gate arm state and cancel any pending recheck timer.

        Call on: disarm (count drops / confidence regresses), gate fire,
        house state change away from HOME_*, coordinator unload.
        """
        self._unidentified_first_seen = None
        if self._guest_persistence_check_handle is not None:
            self._guest_persistence_check_handle()
            self._guest_persistence_check_handle = None

    # ------------------------------------------------------------------
    # v4.7.2 D5: Sustained-occupancy guest signal (Feature B)
    # ------------------------------------------------------------------

    def _discover_guest_rooms(self) -> None:
        """Discover rooms flagged is_guest_room=True and register occupancy listeners.

        Called from async_setup() after _discover_room_sensors().
        Reads CONF_ROOM_IS_GUEST_ROOM and CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN
        from each room entry's options (D4 CONFs). Bug Class #14: reads fresh from
        options each call.

        For each guest room, subscribes to the room's URA occupancy entity
        (binary_sensor.{room_slug}_occupied). Bug Class #38: unsubs stored in
        _guest_room_unsubs; cleaned up on teardown.
        """
        from ..const import (
            CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM,
            CONF_ROOM_IS_GUEST_ROOM, CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
        )

        # Cancel any existing guest-room listeners (handles reconfigure-without-restart).
        for unsub in self._guest_room_unsubs.values():
            try:
                unsub()
            except Exception:
                pass
        self._guest_room_unsubs.clear()
        self._guest_room_state.clear()

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            merged = {**entry.data, **entry.options}
            if not merged.get(CONF_ROOM_IS_GUEST_ROOM, False):
                continue

            room_name = merged.get(CONF_ROOM_NAME, "")
            if not room_name:
                continue

            threshold_min = int(merged.get(CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN, 30))
            room_slug = room_name.lower().replace(" ", "_")
            occupancy_entity_id = f"binary_sensor.{room_slug}_occupied"

            # Initialise anti-flap state for this room.
            self._guest_room_state[room_name] = {
                "first_seen": None,
                "current_occupancy_known": False,
                "threshold_min": threshold_min,
            }

            # Subscribe to the room's URA occupancy sensor.
            # Bug Class #42: listener callback is a bound method; no lambda captures.
            # Bug Class #38: unsub stored for cleanup.
            unsub = async_track_state_change_event(
                self.hass,
                [occupancy_entity_id],
                self._handle_guest_room_occupancy_change,
            )
            self._guest_room_unsubs[room_name] = unsub

            _LOGGER.info(
                "D5 guest room registered: '%s' (threshold=%d min, entity=%s)",
                room_name, threshold_min, occupancy_entity_id,
            )

    @callback
    def _handle_guest_room_occupancy_change(self, event: Any) -> None:
        """Handle occupancy state change for a designated guest room (D5).

        State machine transitions (per plan §4.D5):
        1. Room occupied + occupant unknown → arm first_seen (if None).
        2. Room occupied + occupant known → reset first_seen, set known=True.
        3. Room unoccupied → reset first_seen.

        Bug Class #11: uses dt_util.utcnow() for UTC-aware timestamps.
        Bug Class #42: @callback bound method, not lambda.
        Bug Class #19: async_create_task used for inference scheduling — safe because
        @callback runs on the event loop thread (not a background thread). This matches
        the established pattern at _handle_occupancy_change and _handle_state_change.
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        if new_state.state in _UNAVAILABLE_STATES:
            occupied = False
        else:
            occupied = new_state.state == "on"

        # Identify which guest room this entity belongs to.
        room_name = None
        for rn, state_dict in self._guest_room_state.items():
            rn_slug = rn.lower().replace(" ", "_")
            if f"binary_sensor.{rn_slug}_occupied" == entity_id:
                room_name = rn
                break

        if room_name is None:
            return

        state_dict = self._guest_room_state[room_name]
        now = dt_util.utcnow()

        if not occupied:
            # Transition 3: room unoccupied → reset first_seen.
            if state_dict["first_seen"] is not None:
                _LOGGER.debug(
                    "D5 guest room '%s': went unoccupied — resetting first_seen",
                    room_name,
                )
            state_dict["first_seen"] = None
            state_dict["current_occupancy_known"] = False
        else:
            # Room occupied — check if occupant is known.
            occupant_known = self._is_known_person_in_room(room_name)
            if occupant_known:
                # Transition 2: known person → reset, not a guest signal.
                state_dict["first_seen"] = None
                state_dict["current_occupancy_known"] = True
                _LOGGER.debug(
                    "D5 guest room '%s': known person detected — gate disarmed",
                    room_name,
                )
            else:
                # Transition 1: unknown occupant → arm first_seen if not already set.
                if state_dict["first_seen"] is None:
                    state_dict["first_seen"] = now
                    _LOGGER.info(
                        "D5 guest room '%s': unknown occupant — first_seen armed at %s",
                        room_name, now.isoformat(),
                    )
                state_dict["current_occupancy_known"] = False

        # Trigger inference re-evaluation.
        self.hass.async_create_task(self._run_inference("guest_room_occupancy"))

    def _is_known_person_in_room(self, room_name: str) -> bool:
        """Return True if any known tracked person is currently in the given room.

        Uses person_coordinator's zone tracker if available.
        Falls back to False (unknown = safer for guest detection).
        Bug Class #14: reads fresh from hass.data each call.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return False
            person_coord = manager.coordinators.get("person")
            if person_coord is None:
                return False
            # Check if any tracked person's current location resolves to this room.
            tracked = getattr(person_coord, "_tracked_persons", {})
            for _pid, person_data in tracked.items():
                location = person_data.get("location", "")
                if location and location.lower().replace(" ", "_") == room_name.lower().replace(" ", "_"):
                    return True
        except Exception:
            _LOGGER.debug(
                "D5: could not check known persons in room '%s' (non-fatal)",
                room_name, exc_info=True,
            )
        return False

    def _guest_room_gate_armed(self, now: datetime) -> bool:
        """Evaluate whether any designated guest room triggers the sustained-occupancy gate.

        Returns True if ANY guest room has:
        1. An unknown occupant continuously present for >= threshold_min minutes, AND
        2. The occupant is NOT a known tracked person.

        Exit is immediate: if the condition clears for all rooms, returns False.
        Bug Class #11: uses UTC-aware now parameter.
        """
        for room_name, state_dict in self._guest_room_state.items():
            first_seen = state_dict.get("first_seen")
            if first_seen is None:
                continue
            if state_dict.get("current_occupancy_known", False):
                continue
            threshold_min = state_dict.get("threshold_min", 30)
            elapsed_min = (now - first_seen).total_seconds() / 60.0
            if elapsed_min >= threshold_min:
                _LOGGER.info(
                    "D5 guest room gate fires: room='%s', elapsed=%.1f min (>= %d min)",
                    room_name, elapsed_min, threshold_min,
                )
                return True
        return False

    def _guest_gate_armed(
        self,
        unidentified_count: int,
        census_confidence: str,
        now: datetime,
    ) -> bool:
        """Evaluate all guest-mode entry guards.

        Guards (short-circuit on first failure):
        1. Existence: unidentified_count > 0
        2. Confidence: census_confidence >= _guest_require_confidence
        3. Persistence: unidentified has been seen for >= _guest_persistence_seconds

        On first qualifying tick: arms the gate (sets _unidentified_first_seen)
        and schedules a recheck after persistence_seconds + 5s.
        On non-qualifying tick: disarms (clears state + cancels timer).
        Returns True only when all guards pass.
        """
        # Guard 1: Existence
        if unidentified_count <= 0:
            _LOGGER.debug(
                "Guest gate: no unidentified persons (count=%d) — disarming",
                unidentified_count,
            )
            self._disarm_guest_gate()
            return False

        # Guard 2: Confidence
        if not self._confidence_at_least(census_confidence, self._guest_require_confidence):
            _LOGGER.debug(
                "Guest gate: confidence too low (observed=%s < required=%s) — disarming",
                census_confidence, self._guest_require_confidence,
            )
            self._disarm_guest_gate()
            return False

        # Guard 3: Persistence
        persistence_secs = self._guest_persistence_seconds
        if persistence_secs <= 0:
            # Persistence disabled — fire immediately
            _LOGGER.debug("Guest gate: persistence disabled — firing immediately")
            self._disarm_guest_gate()
            return True

        if self._unidentified_first_seen is None:
            # First qualifying tick — arm the gate
            self._unidentified_first_seen = now
            _LOGGER.info(
                "Guest gate armed: unidentified=%d, confidence=%s — "
                "waiting %ds before firing",
                unidentified_count, census_confidence, persistence_secs,
            )
            # Schedule a forced recheck so we don't depend on census jitter
            self._schedule_guest_persistence_recheck(persistence_secs)
            return False

        elapsed = (now - self._unidentified_first_seen).total_seconds()
        if elapsed >= persistence_secs:
            _LOGGER.info(
                "Guest gate fires: unidentified=%d persisted for %.0fs (>= %ds)",
                unidentified_count, elapsed, persistence_secs,
            )
            # Cancel pending recheck handle — gate is firing now
            if self._guest_persistence_check_handle is not None:
                self._guest_persistence_check_handle()
                self._guest_persistence_check_handle = None
            return True

        _LOGGER.debug(
            "Guest gate: persistence not yet met (%.0f / %d s)",
            elapsed, persistence_secs,
        )
        return False

    def _schedule_guest_persistence_recheck(self, persistence_secs: int) -> None:
        """Schedule a one-shot recheck after the persistence window + 5s buffer.

        Cancelled on disarm, gate fire, or coordinator unload.
        The +5s buffer ensures we always fire AFTER the window, never at its edge.
        """
        from homeassistant.helpers.event import async_call_later

        # Cancel any existing handle first (e.g. if re-armed after partial disarm)
        if self._guest_persistence_check_handle is not None:
            self._guest_persistence_check_handle()
            self._guest_persistence_check_handle = None

        @callback
        def _recheck_callback(_now: datetime) -> None:
            self._guest_persistence_check_handle = None
            self.hass.async_create_task(
                self._run_inference("guest_persistence_recheck")
            )

        self._guest_persistence_check_handle = async_call_later(
            self.hass, persistence_secs + 5, _recheck_callback,
        )
        _LOGGER.debug(
            "Guest persistence recheck scheduled in %ds",
            persistence_secs + 5,
        )

    async def _run_inference(self, trigger: str) -> None:
        """Run state inference and apply transitions.

        v3.6.0.11: Schedules deferred retry when hysteresis blocks.
        """
        if not self._enabled:
            return

        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        # D4: Capture zone modes before inference for change detection
        zone_modes_before = {
            name: tracker.mode for name, tracker in self._zone_trackers.items()
        }

        # v4.7.14: Compute all-persons-away veto signal from person_coordinator.
        # When every configured person.* tracker reports "away" (and the config
        # is non-empty), pass this to infer() so it can veto camera ghost-presence.
        # tracked_count > 0 guard: empty config must not veto (fail-safe).
        # "unknown" is NOT treated as away (conservative — unknown is genuine
        # uncertainty, not confirmed absence).
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        all_tracked_persons_away = False
        tracked_count = 0
        away_person_ids: list[str] = []
        try:
            if person_coordinator and getattr(person_coordinator, "data", None):
                person_data = person_coordinator.data or {}
                tracked_count = len(person_data)
                if tracked_count > 0:
                    all_tracked_persons_away = all(
                        (info.get("location") or "") in ("away", "")
                        for info in person_data.values()
                    )
                    if all_tracked_persons_away:
                        away_person_ids = sorted(person_data.keys())
        except Exception as exc:  # noqa: BLE001 — defensive: stale coord data
            _LOGGER.debug(
                "v4.7.14: failed to compute all_tracked_persons_away: %s", exc
            )
            all_tracked_persons_away = False
            tracked_count = 0
            away_person_ids = []
        # Expose for diagnostics (PresenceHouseStateSensor attributes).
        self._tracked_persons_count = tracked_count
        self._all_tracked_persons_away = all_tracked_persons_away

        any_zone_occupied = any(
            t.mode == ZonePresenceMode.OCCUPIED
            for t in self._zone_trackers.values()
        )

        # v4.7.15 D3: Track sustained-occupancy timer for the WAKING gate.
        # Bug Class #11: UTC-aware timestamps.
        _now_utc = dt_util.utcnow()
        if any_zone_occupied:
            if self._first_positive_zone_occupied_since is None:
                self._first_positive_zone_occupied_since = _now_utc
        else:
            # Cleared on any False — a brief True→False→True burst cannot
            # accumulate sustained seconds (per plan §3 D3 acceptance).
            self._first_positive_zone_occupied_since = None

        current_state = manager.house_state_machine.state

        # v4.6.2.2: Evaluate guest gate (threshold + confidence + persistence)
        # before calling the inference engine. Also clear the arm state when
        # house leaves HOME_* so we don't carry stale arm across state changes.
        now = dt_util.now()
        _home_like_states = (
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
        )
        if current_state not in _home_like_states and current_state != HouseState.GUEST:
            # House is not in a HOME/GUEST state — disarm any pending gate
            if self._unidentified_first_seen is not None:
                _LOGGER.debug(
                    "Guest gate disarmed: house left HOME_* (current=%s)",
                    current_state.value,
                )
                self._disarm_guest_gate()

        # Evaluate the guest gate when in HOME_* states (entry path) or already
        # in GUEST state (hold/exit path).  The unid gate (_guest_gate_armed) has
        # side effects (arms/disarms persistence state) so it is SKIPPED in GUEST
        # state.  The guest_room gate (_guest_room_gate_armed) is a pure predicate
        # with no side effects, so it is safe to evaluate in GUEST state and MUST
        # be evaluated so the exit condition at infer() line 449 gets a truthful
        # value.  Without this, the exit condition reduces to unidentified_count==0
        # which causes immediate GUEST→HOME oscillation on every inference cycle.
        # B1 fix (v4.7.2 reviewer fix-up) — Bug Class #46: Exit-Path Gate Skip.
        if current_state in _home_like_states:
            unid_gate_armed = self._guest_gate_armed(
                unidentified_count=self._unidentified_count,
                census_confidence=self._census_confidence,
                now=now,
            )
            # v4.7.2 D5: Sustained-occupancy guest room path (additive OR).
            # Bug Class #11: D5 timestamps are UTC-aware (dt_util.utcnow()).
            guest_room_gate_armed = self._guest_room_gate_armed(now=dt_util.utcnow())
            guest_armed = unid_gate_armed or guest_room_gate_armed
        elif current_state == HouseState.GUEST:
            # Already in GUEST state — skip unid gate (side-effect-bearing) but
            # evaluate guest_room gate (pure predicate) so the hold/exit decision
            # at infer() line 449 is truthful.
            unid_gate_armed = False
            # Bug Class #11: D5 timestamps are UTC-aware (dt_util.utcnow()).
            guest_room_gate_armed = self._guest_room_gate_armed(now=dt_util.utcnow())
            guest_armed = guest_room_gate_armed
        else:
            unid_gate_armed = False
            guest_room_gate_armed = False
            guest_armed = False

        # v4.7.2 D5: Confidence layering math (plan §7).
        # unid path: 0.8 (existing). guest_room path: 0.9 (higher specificity).
        # max() when both fire; individual when only one fires.
        if guest_room_gate_armed and unid_gate_armed:
            _d5_guest_confidence: float = max(0.8, 0.9)  # = 0.9
        elif guest_room_gate_armed:
            _d5_guest_confidence = 0.9
        else:
            _d5_guest_confidence = 0.8  # unid path only, or neither (ignored)

        new_state = self._inference_engine.infer(
            census_count=self._census_count,
            current_state=current_state,
            any_zone_occupied=any_zone_occupied,
            unidentified_count=self._unidentified_count,
            guest_gate_armed=guest_armed,
            all_tracked_persons_away=all_tracked_persons_away,
        )

        # v4.7.14: log when the person-tracker veto fires to a non-AWAY state.
        if (
            all_tracked_persons_away
            and self._unidentified_count == 0
            and new_state == HouseState.AWAY
            and current_state != HouseState.AWAY
        ):
            _LOGGER.info(
                "v4.7.14: Person-tracker veto fired — all %d tracked persons "
                "away (%s), no unidentified people; forcing AWAY (was %s, "
                "any_zone_occupied=%s)",
                tracked_count,
                ", ".join(away_person_ids) if away_person_ids else "(none)",
                current_state.value,
                any_zone_occupied,
            )

        # Override confidence if transitioning to GUEST via the D5 guest_room path.
        # The inference engine sets 0.8 by default; D5 raises it to 0.9 when warranted.
        if new_state == HouseState.GUEST and guest_room_gate_armed:
            self._inference_engine._confidence = _d5_guest_confidence

        # v4.7.15 D3: WAKING sustained-signal gate (Pattern D).
        # When the engine wants to flip SLEEP→WAKING, require sustained
        # occupancy. A single 03:24 Frigate blip cannot flip WAKING.
        if (
            new_state == HouseState.WAKING
            and current_state == HouseState.SLEEP
        ):
            sustained_seconds = 0
            if self._first_positive_zone_occupied_since is not None:
                sustained_seconds = int(
                    (_now_utc - self._first_positive_zone_occupied_since)
                    .total_seconds()
                )
            wake_decision = self.should_veto_due_to_reliable_signals(
                reliable_signals=[],
                transient_signals=[],
                state_context={
                    "scope": "waking_transition",
                    "house_state": current_state,
                    "sustained_occupancy_seconds": sustained_seconds,
                },
            )
            self._last_veto_decision = wake_decision
            if wake_decision.fired:
                self._wake_blocked_ticks += 1
                _LOGGER.debug(
                    "v4.7.15 D3: WAKING transition blocked — %s",
                    wake_decision.reason,
                )
                new_state = None  # Suppress the WAKING transition this tick.

        # v4.7.15 D3: GUEST exit sustained-signal gate (Pattern E).
        # When the engine wants to flip GUEST → a HOME_* state, require the
        # exit condition (unidentified_count==0 AND not guest_armed) to have
        # persisted for >= _guest_persistence_seconds. Single-frame Frigate
        # FP that drops unidentified_count to 0 momentarily cannot exit GUEST.
        # Mirrors the v4.6.2.2 entry-side persistence symmetrically.
        if (
            current_state == HouseState.GUEST
            and new_state is not None
            and new_state != HouseState.GUEST
            and new_state in (
                HouseState.HOME_DAY,
                HouseState.HOME_EVENING,
                HouseState.HOME_NIGHT,
            )
        ):
            # The condition for exit must currently be true (otherwise infer()
            # wouldn't have returned a HOME_* state). Track first-seen time.
            if self._guest_exit_quiet_since is None:
                self._guest_exit_quiet_since = _now_utc
            quiet_seconds = int(
                (_now_utc - self._guest_exit_quiet_since).total_seconds()
            )
            exit_decision = self.should_veto_due_to_reliable_signals(
                reliable_signals=[],
                transient_signals=[],
                state_context={
                    "scope": "guest_exit",
                    "house_state": current_state,
                    "guest_exit_quiet_seconds": quiet_seconds,
                    # guest_persistence_seconds: helper will fall back to
                    # self._guest_persistence_seconds if omitted (symmetric).
                },
            )
            self._last_veto_decision = exit_decision
            if exit_decision.fired:
                _LOGGER.debug(
                    "v4.7.15 D3: GUEST exit blocked — %s", exit_decision.reason,
                )
                new_state = None  # Suppress the GUEST exit this tick.
            else:
                # Exit sustained — clear the timer so the next GUEST entry
                # restarts from None.
                self._guest_exit_quiet_since = None
        else:
            # Either not in GUEST, or engine did not signal exit — reset timer.
            if current_state != HouseState.GUEST or new_state == HouseState.GUEST:
                self._guest_exit_quiet_since = None

        if new_state is not None:
            accepted = manager.house_state_machine.transition(
                new_state, trigger=trigger
            )
            if accepted:
                # Clear any pending retry — transition succeeded
                if self._retry_unsub is not None:
                    self._retry_unsub()
                    self._retry_unsub = None

                # v4.6.2.2: If we just transitioned INTO guest mode, clear the
                # arm state (gate fired successfully — no need to keep the timer).
                if new_state == HouseState.GUEST:
                    self._disarm_guest_gate()
                # If we just transitioned OUT of guest mode (exit path),
                # also clear any residual arm state.
                elif current_state == HouseState.GUEST:
                    self._disarm_guest_gate()

                await self._count_transition()

                # Propagate sleep state to zones
                if new_state == HouseState.SLEEP:
                    for tracker in self._zone_trackers.values():
                        tracker.set_sleep(True)
                elif current_state == HouseState.SLEEP:
                    for tracker in self._zone_trackers.values():
                        tracker.set_sleep(False)

                # Log decision (house-scoped)
                await self._log_state_transition(
                    current_state, new_state, trigger
                )

                # D3: Log house state change to database
                db = self.hass.data.get(DOMAIN, {}).get("database")
                if db is not None:
                    self.hass.async_create_task(
                        db.log_house_state_change(
                            state=new_state.value,
                            confidence=self._inference_engine.confidence,
                            trigger=trigger,
                            previous_state=current_state.value,
                        )
                    )

                # Publish signal
                from homeassistant.helpers.dispatcher import (
                    async_dispatcher_send,
                )
                # v3.21.1 D1: Observation mode — inference runs but signal
                # dispatch is suppressed so downstream coordinators don't react.
                if self.observation_mode:
                    _LOGGER.info(
                        "[observation mode] Presence would dispatch "
                        "SIGNAL_HOUSE_STATE_CHANGED %s → %s (trigger=%s) — suppressed",
                        current_state.value,
                        new_state.value,
                        trigger,
                    )
                else:
                    async_dispatcher_send(
                        self.hass,
                        SIGNAL_HOUSE_STATE_CHANGED,
                        {
                            "old_state": current_state.value,
                            "new_state": new_state.value,
                            "trigger": trigger,
                            "confidence": self._inference_engine.confidence,
                        },
                    )

                    # Activity log: house state transition
                    activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                    if activity_logger:
                        self.hass.async_create_task(
                            activity_logger.log(
                                coordinator="presence",
                                action="house_state_change",
                                description=f"House state {current_state.value} -> {new_state.value} (trigger={trigger})",
                                importance="notable",
                                details={
                                    "old_state": current_state.value,
                                    "new_state": new_state.value,
                                    "trigger": trigger,
                                    "confidence": self._inference_engine.confidence,
                                },
                            )
                        )

                # House-level anomaly detection
                # v4.6.3 D3/D11/D12: Use canonical AnomalyEvent + ActivityLogger.
                if self.anomaly_detector is not None:
                    anomaly = self.anomaly_detector.record_observation(
                        "census_count",
                        DIAGNOSTICS_SCOPE_HOUSE,
                        float(self._census_count),
                    )
                    if anomaly:
                        # v4.6.3.3: SUPPRESS anomaly_log persistence + ActivityLogger emit for
                        # census_count. Same degenerate-shape problem as v4.6.3.1's zone_occupancy
                        # suppression: census_count is a low-cardinality integer (0-N people)
                        # that is mostly 0 during sleep/away or 1-4 when occupied. With
                        # minimum_samples=24 and Z_SCORE_ADVISORY=2.0, any "person appears"
                        # tick during a mostly-empty period produces a high z-score on every
                        # observation, so v4.6.3 D3's persistence path emitted 1825 anomalies
                        # in 24h after v4.6.3.1 suppressed zone_occupancy.
                        # In-memory tracking via record_observation() above is preserved, so the
                        # per-coordinator anomaly sensor (sensor.ura_presence_coordinator_presence_anomaly)
                        # still counts these. They just don't pollute anomaly_log.
                        # Proper fix (deferred to a future cycle): drop census_count from
                        # PRESENCE_METRICS entirely; use Bayesian time-bin distributions
                        # for census patterns (mirrors the v4.6.2 routine-awareness shape).
                        _LOGGER.debug(
                            "Presence census_count in-memory anomaly only (persistence suppressed): "
                            "severity=%s z=%.2f count=%d",
                            anomaly.severity.value, anomaly.z_score, self._census_count,
                        )

                # Outcome measurement: record for accuracy tracking
                self._record_outcome(current_state, new_state, trigger)

            else:
                # Transition blocked (likely hysteresis) — schedule retry
                remaining = manager.house_state_machine.remaining_hysteresis()
                if remaining > 0 and trigger != "deferred_retry":
                    self._schedule_deferred_retry(remaining + 1)

        # D4: Log zone mode changes to database
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is not None:
            for zone_name, tracker in self._zone_trackers.items():
                old_mode = zone_modes_before.get(zone_name)
                new_mode = tracker.mode
                if old_mode is not None and old_mode != new_mode:
                    occupied_rooms = [
                        rn for rn, occ in tracker._room_occupied.items() if occ
                    ]
                    self.hass.async_create_task(
                        db.log_zone_event(
                            zone=zone_name,
                            event_type=new_mode,
                            room_count=len(occupied_rooms),
                            rooms=occupied_rooms if occupied_rooms else None,
                        )
                    )

        # Zone-scoped anomaly detection (runs every inference, not just on transition)
        await self._check_zone_anomalies()

        # v4.5.20: fire per-cycle refresh signal so PresenceAnomalySensor
        # (and any other sensor subscribed) re-renders attrs without
        # waiting for HA to naturally re-query. Mirrors HVAC/Safety/
        # Security pattern. Function-local import keeps Presence's
        # import surface minimal.
        try:
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            from .signals import SIGNAL_PRESENCE_ENTITIES_UPDATE
            async_dispatcher_send(self.hass, SIGNAL_PRESENCE_ENTITIES_UPDATE)
        except Exception:
            _LOGGER.warning(
                "Presence: failed to dispatch SIGNAL_PRESENCE_ENTITIES_UPDATE",
                exc_info=True,
            )

    async def _check_zone_anomalies(self) -> None:
        """Record zone-level anomaly observations.

        Checks each zone's occupied status and records it as an observation
        for zone-scoped anomaly detection. Detects unusual occupancy patterns
        like "zone occupied at unusual time."
        """
        if self.anomaly_detector is None:
            return

        hour = dt_util.now().hour
        for zone_name, tracker in self._zone_trackers.items():
            if not tracker.has_sensors:
                continue
            scope = f"zone:{zone_name}"
            # Record occupancy as 1.0/0.0 observation for time-of-day baseline
            occupied_value = 1.0 if tracker.mode == ZonePresenceMode.OCCUPIED else 0.0
            anomaly = self.anomaly_detector.record_observation(
                "zone_occupied_count",
                scope,
                occupied_value,
            )
            if anomaly:
                # v4.6.3.1: SUPPRESS anomaly_log persistence + ActivityLogger emit for
                # zone_occupied_count. Binary 0/1 occupancy is a degenerate input to
                # z-score detection: a rarely-occupied zone develops mean ≈ occupancy_ratio
                # and std ≈ sqrt(p*(1-p)), so every "occupied=1.0" observation produces
                # z >= 4 → CRITICAL. v4.6.3 D3 wired this through save_anomaly_event,
                # which produced 2117 emits in 3h post-deploy.
                # In-memory tracking via record_observation() above is preserved, so the
                # per-coordinator anomaly sensor (sensor.ura_presence_coordinator_presence_anomaly)
                # still counts these. They just don't pollute anomaly_log.
                # Proper fix (deferred to a future cycle): drop zone_occupied_count from
                # PRESENCE_METRICS entirely; use Bayesian time-bin distributions for
                # occupancy patterns instead (v4.6.2 routine-awareness already uses this
                # shape for per-person routines).
                _LOGGER.debug(
                    "Zone %s in-memory anomaly only (zone_occupancy persistence suppressed): "
                    "severity=%s z=%.2f",
                    zone_name, anomaly.severity.value, anomaly.z_score,
                )

    async def _log_zone_mode_change(
        self,
        zone_name: str,
        old_mode: str,
        new_mode: str,
        trigger: str,
    ) -> None:
        """Log a zone mode change as a decision (zone-scoped)."""
        if self.decision_logger is None:
            return

        decision = DecisionLog(
            timestamp=dt_util.utcnow(),
            coordinator_id=self.coordinator_id,
            decision_type="zone_mode_change",
            scope=f"zone:{zone_name}",
            situation_classified=new_mode,
            urgency=30,
            confidence=0.9,
            context={
                "zone_name": zone_name,
                "old_mode": old_mode,
                "new_mode": new_mode,
                "trigger": trigger,
            },
        )
        await self.decision_logger.log_decision(decision)

    async def _count_transition(self) -> None:
        """Count daily transitions and record observation for anomaly detection.

        v4.6.4 P1: `transition_count_daily` was declared in PRESENCE_METRICS since
        v3.6.0-c1 but never had a `record_observation` call site. The metric is
        well-shaped — monotone within day (0,1,2…), resets at midnight — so
        z-score persistence is safe (no degenerate-shape risk like census_count /
        zone_occupied_count which were suppressed in v4.6.3.3 / v4.6.3.1).
        """
        today = dt_util.now().date().isoformat()
        if today != self._transition_reset_date:
            self._transitions_today = 0
            self._transition_reset_date = today
            # v3.19.0: Reset face arrival counters at midnight
            for tracker in self._zone_trackers.values():
                tracker._face_arrivals_today = 0
            self._face_arrival_cooldown.clear()
        self._transitions_today += 1

        # v4.6.4 P1: record and emit if anomalously high transition count
        if self.anomaly_detector is None:
            return
        anomaly = self.anomaly_detector.record_observation(
            "transition_count_daily",
            DIAGNOSTICS_SCOPE_HOUSE,
            float(self._transitions_today),
        )
        if not anomaly:
            return
        from .anomaly_event import (
            AnomalyEvent,
            AnomalySeverity as _NewSev,
            AnomalyType,
            build_context_json,
            map_diag_severity,
        )
        _ctx = build_context_json(
            source_signal="SIGNAL_HOUSE_STATE_CHANGED",
            extra={
                "transitions_today": self._transitions_today,
            },
        )
        _event = AnomalyEvent(
            coordinator="presence",
            type="presence.transition_count_daily",
            # v4.6.6 D1: 1:1 mapping preserves all 4 z-score bands.
            severity=map_diag_severity(anomaly.severity),
            anomaly_type=AnomalyType.POINT_IN_TIME,
            detected_at=anomaly.timestamp.isoformat(),
            payload=_ctx,
            observed_value=anomaly.observed_value,
            expected_mean=anomaly.expected_mean,
            expected_std=anomaly.expected_std,
            z_score=round(anomaly.z_score, 3),
            sample_size=anomaly.sample_size,
        )
        await self.anomaly_detector.store_event(_event)
        _LOGGER.info(
            "Presence transition_count_daily anomaly: z=%.2f count=%d severity=%s",
            anomaly.z_score, self._transitions_today, anomaly.severity.value,
        )
        _activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
        if _activity_logger:
            await _activity_logger.log(
                coordinator="presence",
                action="anomaly",
                description=(
                    f"Presence transition_count_daily anomaly z={anomaly.z_score:.2f} "
                    f"count={self._transitions_today}"
                ),
                importance="notable",
                details={
                    "type": "presence.transition_count_daily",
                    "z_score": round(anomaly.z_score, 3),
                    "transitions_today": self._transitions_today,
                },
            )

    # ------------------------------------------------------------------
    # Outcome measurement
    # ------------------------------------------------------------------

    def _record_outcome(
        self,
        old_state: HouseState,
        new_state: HouseState,
        trigger: str,
    ) -> None:
        """Record a state transition outcome for accuracy tracking.

        Tracks detection accuracy by measuring how often transitions are
        later contradicted (e.g., went to AWAY but immediately came back).
        """
        now = dt_util.utcnow()

        # Track if previous transition was contradicted
        if hasattr(self, '_last_transition_time') and self._last_transition_state is not None:
            elapsed = (now - self._last_transition_time).total_seconds()
            if elapsed < 120:  # Contradiction within 2 minutes
                self._outcome_false_positives += 1
                _LOGGER.debug(
                    "Potential false positive: %s lasted only %.0fs before %s",
                    self._last_transition_state.value, elapsed, new_state.value,
                )
            else:
                self._outcome_true_positives += 1

        self._last_transition_state = new_state
        self._last_transition_time = now

    @property
    def detection_accuracy(self) -> float:
        """Return detection accuracy as ratio of true positives to total."""
        total = self._outcome_true_positives + self._outcome_false_positives
        if total == 0:
            return 1.0
        return self._outcome_true_positives / total

    @property
    def false_positive_rate(self) -> float:
        """Return false positive rate."""
        total = self._outcome_true_positives + self._outcome_false_positives
        if total == 0:
            return 0.0
        return self._outcome_false_positives / total

    # ------------------------------------------------------------------
    # Decision logging
    # ------------------------------------------------------------------

    async def _log_state_transition(
        self,
        old_state: HouseState,
        new_state: HouseState,
        trigger: str,
    ) -> None:
        """Log a state transition as a decision."""
        if self.decision_logger is None:
            return

        decision = DecisionLog(
            timestamp=dt_util.utcnow(),
            coordinator_id=self.coordinator_id,
            decision_type="state_transition",
            scope=DIAGNOSTICS_SCOPE_HOUSE,
            situation_classified=new_state.value,
            urgency=50,
            confidence=self._inference_engine.confidence,
            context={
                "old_state": old_state.value,
                "new_state": new_state.value,
                "trigger": trigger,
                "census_count": self._census_count,
                "zones": {
                    name: tracker.mode
                    for name, tracker in self._zone_trackers.items()
                },
            },
        )
        await self.decision_logger.log_decision(decision)

    async def evaluate(
        self,
        intents: list,
        context: dict,
    ) -> List[CoordinatorAction]:
        """Evaluate intents — Presence doesn't generate actions directly.

        Presence is informational: it publishes state, other coordinators
        react to it. But we still process intents if any are routed to us.
        """
        return []

    async def async_teardown(self) -> None:
        """Tear down the Presence Coordinator."""
        # Cancel deferred retry timer
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

        # v4.6.2.2: Cancel guest persistence recheck timer on teardown (Bug Class #19)
        self._disarm_guest_gate()

        # v4.7.2 D5: Cancel guest-room occupancy listeners (Bug Class #38)
        for unsub in self._guest_room_unsubs.values():
            try:
                unsub()
            except Exception:
                pass
        self._guest_room_unsubs.clear()
        self._guest_room_state.clear()

        self._cancel_listeners()

        # Save anomaly baselines
        if self.anomaly_detector is not None:
            await self.anomaly_detector.save_baselines()

        _LOGGER.info("Presence Coordinator torn down")

    # ------------------------------------------------------------------
    # Override controls (backing select entities + services)
    # ------------------------------------------------------------------

    def set_house_state_override(self, state_value: str) -> None:
        """Set house state override from select entity or service call.

        Called by select entity when user changes the dropdown,
        or by ura.set_house_state service.
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        if state_value == "auto":
            manager.house_state_machine.clear_override()
            # Clear zone sleep overrides too
            for tracker in self._zone_trackers.values():
                if tracker._override == ZonePresenceMode.SLEEP:
                    tracker.clear_override()
        else:
            try:
                house_state = HouseState(state_value)
                manager.house_state_machine.set_override(house_state)

                # Propagate AWAY to all zones
                if house_state == HouseState.AWAY:
                    for tracker in self._zone_trackers.values():
                        tracker.set_override(ZonePresenceMode.AWAY)
                elif house_state == HouseState.SLEEP:
                    for tracker in self._zone_trackers.values():
                        tracker.set_sleep(True)
            except ValueError:
                _LOGGER.warning("Invalid house state override: %s", state_value)

    def get_house_state_override(self) -> str:
        """Get current house state override value for select entity."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None or not manager.house_state_machine.is_overridden:
            return "auto"
        return manager.house_state_machine.state.value

    # ------------------------------------------------------------------
    # Geofence signal (v3.6.0-c1.1: wired to person.* state changes)
    # ------------------------------------------------------------------

    def handle_geofence_event(self, person_id: str, zone: str) -> None:
        """Handle geofence enter/leave event for a person.

        When a person's device tracker transitions to/from 'home',
        triggers inference for state re-evaluation.

        v3.6.0.11: Triggers from any state on arrival, not just AWAY.
        The inference engine determines the valid transition.
        """
        if zone == "home":
            # Person arriving — trigger inference from any state
            self.hass.async_create_task(self._run_inference("geofence_arrive"))
            _LOGGER.info("Geofence: %s arrived home", person_id)
        elif zone == "not_home":
            # Person left — trigger inference to check if house is now empty
            self.hass.async_create_task(self._run_inference("geofence_leave"))
            _LOGGER.debug("Geofence: %s left home", person_id)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_diagnostics_summary(self) -> dict[str, Any]:
        """Return full presence diagnostics."""
        summary = super().get_diagnostics_summary()
        summary["census_count"] = self._census_count
        summary["unidentified_count"] = self._unidentified_count
        summary["house_state"] = self.house_state
        summary["confidence"] = self.confidence
        summary["transitions_today"] = self._transitions_today
        summary["detection_accuracy"] = round(self.detection_accuracy, 3)
        summary["false_positive_rate"] = round(self.false_positive_rate, 3)
        summary["outcome_stats"] = {
            "true_positives": self._outcome_true_positives,
            "false_positives": self._outcome_false_positives,
        }
        summary["zones"] = {
            name: tracker.to_dict()
            for name, tracker in self._zone_trackers.items()
        }
        return summary
