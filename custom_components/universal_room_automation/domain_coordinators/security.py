"""Security Coordinator — armed state, entry monitoring, lock control, camera triggers.

Manages armed states, entry sensor monitoring, lock control, security camera
recording triggers, and periodic lock compliance checks. Second active-control
coordinator after Safety (priority 80).

v3.6.0-c3: Initial implementation.

Key design decisions:
  - All locks, lights, cameras manually configured — no auto-discovery (req #1, #5)
  - Camera recording disabled by default (req #2)
  - Coordinator can be disabled entirely (req #3)
  - Armed state flag, optionally coupled to alarm panel (req #4)
  - Auto-follow house state off by default (req #6)
  - Unknown person detection → lock all doors (req #7)
  - Periodic lock check at configurable interval, armed-independent (req #8)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_SECURITY_ALARM_PANEL,
    CONF_SECURITY_AUTO_FOLLOW,
    CONF_SECURITY_CAMERA_ENTITIES,
    CONF_SECURITY_CAMERA_RECORD_DURATION,
    CONF_SECURITY_CAMERA_RECORDING,
    CONF_SECURITY_DELEGATE_LIGHTS_TO_NM,
    CONF_SECURITY_ENTRY_SENSORS,
    CONF_SECURITY_GARAGE_ENTITIES,
    CONF_SECURITY_LIGHT_ENTITIES,
    CONF_SECURITY_LOCK_CHECK_INTERVAL,
    CONF_SECURITY_LOCK_ENTITIES,
    DOMAIN,
    SECURITY_AUTO_FOLLOW_ARM_DELAY_S,
)
from .base import (
    BaseCoordinator,
    CoordinatorAction,
    Intent,
    NotificationAction,
    ServiceCallAction,
    Severity,
)
from .coordinator_diagnostics import DailyCounter
from .signals import (
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_OPTIMIZER_INTENT,
    SIGNAL_OPTIMIZER_INTENT_VETO,
    SIGNAL_PERSON_ARRIVING,
    SIGNAL_SAFETY_HAZARD,
    SIGNAL_SECURITY_ENTITIES_UPDATE,
    SIGNAL_SECURITY_EVENT,
    SecurityEvent as SecurityEventPayload,
)

_LOGGER = logging.getLogger(__name__)

# Metrics tracked by anomaly detection
SECURITY_METRICS = ["alert_trigger_frequency", "entry_anomaly_score"]

# v4.6.5.1 P2: Module-level suppression registry — every metric in
# SECURITY_METRICS must be EITHER wired (have a record_observation call site
# in security.py) OR listed here. Introspected by the parametric meta-test
# in test_v465_observability_gap.py.
#
# - entry_anomaly_score: defined in SECURITY_METRICS but no record_observation
#   call site exists — silent slot. Documented per v4.6.3.1 doctrine.
SECURITY_SUPPRESSED_FROM_PERSISTENCE: frozenset[str] = frozenset({
    "entry_anomaly_score",
})


# ============================================================================
# Enums
# ============================================================================


class ArmedState(StrEnum):
    DISARMED = "disarmed"
    ARMED_HOME = "armed_home"
    ARMED_AWAY = "armed_away"
    ARMED_VACATION = "armed_vacation"


class _SecurityAggStatus(StrEnum):
    """v4.6.9 D2 — overall status vocabulary for SecurityAggregatorSensor.

    Bug Class #22 guard: StrEnum; never raw string literals in the sensor.
    """

    ARMED = "armed"
    DISARMED = "disarmed"
    PARTIAL = "partial"
    ALERT = "alert"


class EntryVerdict(StrEnum):
    SANCTIONED = "sanctioned"
    NOTIFY = "notify"
    LOG_ONLY = "log_only"
    INVESTIGATE = "investigate"
    ALERT = "alert"
    ALERT_HIGH = "alert_high"


# Map HA alarm panel states to ArmedState
_ALARM_STATE_MAP: dict[str, ArmedState] = {
    "disarmed": ArmedState.DISARMED,
    "armed_home": ArmedState.ARMED_HOME,
    "armed_away": ArmedState.ARMED_AWAY,
    "armed_vacation": ArmedState.ARMED_VACATION,
    "armed_night": ArmedState.ARMED_HOME,
    "armed_custom_bypass": ArmedState.ARMED_HOME,
}

# Map ArmedState to alarm panel service
_ARMED_TO_ALARM_SERVICE: dict[ArmedState, str] = {
    ArmedState.DISARMED: "alarm_disarm",
    ArmedState.ARMED_HOME: "alarm_arm_home",
    ArmedState.ARMED_AWAY: "alarm_arm_away",
    ArmedState.ARMED_VACATION: "alarm_arm_vacation",
}

# House-State Rung 2a — canonical house_state string → ArmedState mapping.
# Single source of truth used by ``_handle_house_state_intent`` (debounce
# scheduler) and ``_fire_state_driven_arming`` (fire path).
#
# Fix-up A-H3: restricted to the plan's rung-2a table only. HOME_* / SLEEP
# transitions are DELIBERATELY UNMAPPED — treated as no-ops (rung 2b
# territory, deferred). This also resolves B-H2 boot-noise: HOME_*
# transitions produced by presence post-boot no longer trigger any arming
# action because they never resolve to an ArmedState.
_HOUSE_STATE_TO_ARMED: dict[str, ArmedState] = {
    "away": ArmedState.ARMED_AWAY,
    "vacation": ArmedState.ARMED_VACATION,
    "guest": ArmedState.ARMED_HOME,
    "arriving": ArmedState.DISARMED,
    "waking": ArmedState.DISARMED,
}

# INV-4: NM severity for state-driven arming transitions — DIRECTION-aware
# (A-M3 fix-up). Escalation (moving to a stricter posture) is HIGH so the
# operator sees it; de-escalation (relaxing, or DISARM) is MEDIUM. The
# ordering below defines "stricter":
#   DISARMED (0) < ARMED_HOME (1) < ARMED_AWAY (2) < ARMED_VACATION (3)
# Under this rule guest-arm (DISARMED→ARMED_HOME) is correctly HIGH; a
# flat per-target map would have called it MEDIUM.
_ARMED_STRICTNESS: dict[ArmedState, int] = {
    ArmedState.DISARMED: 0,
    ArmedState.ARMED_HOME: 1,
    ArmedState.ARMED_AWAY: 2,
    ArmedState.ARMED_VACATION: 3,
}


def _state_driven_severity(from_state: ArmedState, to_state: ArmedState) -> Severity:
    """Return NM severity for an auto-follow arming transition.

    HIGH when ``to_state`` is stricter than ``from_state`` (escalation);
    MEDIUM otherwise (de-escalation or same-rank move). Same-rank cannot
    happen in the fire path because same-target transitions short-circuit
    with ``suppressed="noop"`` before we notify.
    """
    if _ARMED_STRICTNESS.get(to_state, 0) > _ARMED_STRICTNESS.get(from_state, 0):
        return Severity.HIGH
    return Severity.MEDIUM

# Verdict → severity mapping
_VERDICT_SEVERITY: dict[EntryVerdict, Severity] = {
    EntryVerdict.SANCTIONED: Severity.LOW,
    EntryVerdict.LOG_ONLY: Severity.LOW,
    EntryVerdict.NOTIFY: Severity.LOW,
    EntryVerdict.INVESTIGATE: Severity.MEDIUM,
    EntryVerdict.ALERT: Severity.HIGH,
    EntryVerdict.ALERT_HIGH: Severity.CRITICAL,
}


# ============================================================================
# Helper classes
# ============================================================================


@dataclass
class EntryEvent:
    """Represents a door/window open event."""

    entity_id: str
    timestamp: datetime = field(default_factory=dt_util.utcnow)
    new_state: str = "on"
    old_state: str = "off"


class SanctionChecker:
    """Checks census/person data to classify entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._expected_arrivals: dict[str, datetime] = {}
        self._authorized_guests: dict[str, datetime] = {}

    def add_expected_arrival(self, person_id: str, window_minutes: int = 30) -> None:
        """Add a person to the expected arrivals list."""
        self._expected_arrivals[person_id] = dt_util.utcnow() + timedelta(
            minutes=window_minutes
        )

    def authorize_guest(self, person_name: str, expires_hours: float = 24) -> None:
        """Add an authorized guest."""
        self._authorized_guests[person_name] = dt_util.utcnow() + timedelta(
            hours=expires_hours
        )

    def check_entry(self, context: dict[str, Any]) -> EntryVerdict:
        """Evaluate an entry event against census data."""
        now = dt_util.utcnow()

        # Clean expired entries
        self._expected_arrivals = {
            k: v for k, v in self._expected_arrivals.items() if v > now
        }
        self._authorized_guests = {
            k: v for k, v in self._authorized_guests.items() if v > now
        }

        census = context.get("census", {})

        # Validate census freshness — stale data (>5 min) should not be trusted
        census_ts = census.get("timestamp")
        if census_ts:
            try:
                ts = datetime.fromisoformat(census_ts) if isinstance(census_ts, str) else census_ts
                age = (now - ts).total_seconds()
                if age > 300:  # 5 minutes
                    _LOGGER.warning("Census data stale (%.0fs old), treating as uncertain", age)
                    return EntryVerdict.INVESTIGATE
            except (ValueError, TypeError):
                pass
        persons_home = census.get("persons_home", [])
        unknown_present = census.get("unknown_present", False)

        # Unknown person → highest alert
        if unknown_present:
            return EntryVerdict.ALERT_HIGH

        # Check expected arrivals
        if self._expected_arrivals:
            return EntryVerdict.SANCTIONED

        # Check authorized guests
        if self._authorized_guests:
            return EntryVerdict.SANCTIONED

        # Known persons home → sanctioned
        if persons_home:
            return EntryVerdict.SANCTIONED

        # Nobody home and door opens → investigate
        return EntryVerdict.INVESTIGATE

    def get_expected_arrivals_snapshot(self) -> list[dict[str, Any]]:
        """Return current expected arrivals for sensor exposure."""
        now = dt_util.utcnow()
        result = []
        for person_id, expires in self._expected_arrivals.items():
            if expires > now:
                result.append({
                    "person_id": person_id,
                    "expires": expires.isoformat(),
                    "minutes_remaining": round((expires - now).total_seconds() / 60, 1),
                })
        return result

    def get_authorized_guests_snapshot(self) -> list[dict[str, Any]]:
        """Return current authorized guests for sensor exposure."""
        now = dt_util.utcnow()
        result = []
        for name, expires in self._authorized_guests.items():
            if expires > now:
                result.append({
                    "guest_name": name,
                    "expires": expires.isoformat(),
                    "hours_remaining": round((expires - now).total_seconds() / 3600, 1),
                })
        return result

    def has_unknown_persons(self, context: dict[str, Any]) -> bool:
        """Check if unknown persons are detected."""
        census = context.get("census", {})
        return census.get("unknown_present", False)


class EntryProcessor:
    """Evaluates door/window events against armed state and census."""

    def __init__(
        self,
        hass: HomeAssistant,
        sanction_checker: SanctionChecker,
    ) -> None:
        self.hass = hass
        self._sanction_checker = sanction_checker

    def evaluate_entry(
        self,
        event: EntryEvent,
        armed_state: ArmedState,
        context: dict[str, Any],
    ) -> EntryVerdict:
        """Evaluate an entry event and return a verdict."""
        if armed_state == ArmedState.DISARMED:
            # Even when disarmed, unknown persons trigger alert
            if self._sanction_checker.has_unknown_persons(context):
                return EntryVerdict.ALERT_HIGH
            return EntryVerdict.LOG_ONLY

        # Armed — run full sanction check
        verdict = self._sanction_checker.check_entry(context)

        # Escalate based on armed level
        if armed_state in (ArmedState.ARMED_AWAY, ArmedState.ARMED_VACATION):
            if verdict == EntryVerdict.INVESTIGATE:
                verdict = EntryVerdict.ALERT
            elif verdict == EntryVerdict.NOTIFY:
                verdict = EntryVerdict.INVESTIGATE

        return verdict


class CameraRecordDispatcher:
    """Dispatches recording triggers to cameras based on detected platform."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._camera_platforms: dict[str, str] = {}

    async def async_setup(self, camera_entities: list[str]) -> None:
        """Detect camera platforms from entity registry."""
        try:
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(self.hass)
            for entity_id in camera_entities:
                entry = registry.async_get(entity_id)
                if entry is not None:
                    platform = entry.platform or "generic"
                    self._camera_platforms[entity_id] = platform
                    _LOGGER.debug(
                        "Camera %s detected as platform: %s", entity_id, platform
                    )
                else:
                    self._camera_platforms[entity_id] = "generic"
        except Exception:
            _LOGGER.warning("Failed to detect camera platforms, using generic")
            for entity_id in camera_entities:
                self._camera_platforms[entity_id] = "generic"

    def _build_camera_actions(
        self,
        camera_entities: list[str],
        duration: int = 30,
    ) -> list[ServiceCallAction]:
        """Generate platform-aware service call actions for camera recording."""
        actions: list[ServiceCallAction] = []
        for entity_id in camera_entities:
            platform = self._camera_platforms.get(entity_id, "generic")
            action = self._build_record_action(entity_id, platform, duration)
            if action:
                actions.append(action)
        return actions

    def _build_record_action(
        self,
        entity_id: str,
        platform: str,
        duration: int,
    ) -> ServiceCallAction | None:
        """Build platform-specific recording action."""
        if platform == "frigate":
            return ServiceCallAction(
                coordinator_id="security",
                target_device=entity_id,
                severity=Severity.HIGH,
                service="frigate.record",
                service_data={"entity_id": entity_id, "duration": duration},
                description=f"Frigate record trigger on {entity_id}",
            )
        elif platform == "unifiprotect":
            return ServiceCallAction(
                coordinator_id="security",
                target_device=entity_id,
                severity=Severity.HIGH,
                service="unifiprotect.set_recording_mode",
                service_data={"entity_id": entity_id, "recording_mode": "always"},
                description=f"UniFi Protect record trigger on {entity_id}",
            )
        elif platform == "reolink":
            return ServiceCallAction(
                coordinator_id="security",
                target_device=entity_id,
                severity=Severity.HIGH,
                service="camera.record",
                service_data={
                    "entity_id": entity_id,
                    "duration": duration,
                },
                description=f"Reolink record trigger on {entity_id}",
            )
        else:
            # Generic HA camera.record
            return ServiceCallAction(
                coordinator_id="security",
                target_device=entity_id,
                severity=Severity.HIGH,
                service="camera.record",
                service_data={
                    "entity_id": entity_id,
                    "duration": duration,
                },
                description=f"Camera record trigger on {entity_id}",
            )


class SecurityPatternLearner:
    """Learns normal entry patterns per entry point using MetricBaseline."""

    MINIMUM_DAYS = 30

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._entry_history: dict[str, list[datetime]] = defaultdict(list)
        self._start_time: datetime = dt_util.utcnow()

    @property
    def learning_active(self) -> bool:
        """Return True if enough data has been collected."""
        elapsed = dt_util.utcnow() - self._start_time
        return elapsed.days >= self.MINIMUM_DAYS

    def record_entry(self, entity_id: str) -> None:
        """Record an entry event for pattern learning."""
        self._entry_history[entity_id].append(dt_util.utcnow())
        # Keep last 90 days
        cutoff = dt_util.utcnow() - timedelta(days=90)
        self._entry_history[entity_id] = [
            ts for ts in self._entry_history[entity_id] if ts > cutoff
        ]

    def is_anomalous(self, entity_id: str) -> bool:
        """Check if a current entry is anomalous based on historical patterns."""
        if not self.learning_active:
            return False

        history = self._entry_history.get(entity_id, [])
        if len(history) < 10:
            return False

        now = dt_util.utcnow()
        current_hour = now.hour

        # Count entries at this hour historically
        hour_counts: dict[int, int] = defaultdict(int)
        for ts in history:
            hour_counts[ts.hour] += 1

        total = sum(hour_counts.values())
        if total == 0:
            return False

        hour_ratio = hour_counts.get(current_hour, 0) / total
        # If less than 2% of entries happen at this hour, it's anomalous
        return hour_ratio < 0.02


# ============================================================================
# Main Coordinator
# ============================================================================


class SecurityCoordinator(BaseCoordinator):
    """Security Coordinator — armed state, entry monitoring, lock control.

    Priority 80: below Safety (100), above Energy/HVAC/Comfort.
    """

    COORDINATOR_ID = "security"
    PRIORITY = 80

    def __init__(
        self,
        hass: HomeAssistant,
        lock_entities: list[str] | None = None,
        garage_entities: list[str] | None = None,
        entry_sensors: list[str] | None = None,
        security_lights: list[str] | None = None,
        camera_entities: list[str] | None = None,
        camera_recording_enabled: bool = False,
        camera_record_duration: int = 30,
        alarm_panel_entity: str | None = None,
        auto_follow_house_state: bool = False,
        lock_check_interval: int = 30,
        delegate_lights_to_nm: bool = True,
    ) -> None:
        """Initialize the Security Coordinator."""
        super().__init__(
            hass,
            coordinator_id=self.COORDINATOR_ID,
            name="Security Coordinator",
            priority=self.PRIORITY,
        )
        self._armed_state = ArmedState.DISARMED
        self._lock_entities = lock_entities or []
        self._garage_entities = garage_entities or []
        self._entry_sensors = entry_sensors or []
        self._security_light_entities = security_lights or []
        self._camera_entities = camera_entities or []
        self._camera_recording_enabled = camera_recording_enabled
        self._camera_record_duration = camera_record_duration
        self._alarm_panel_entity = alarm_panel_entity
        self._auto_follow_house_state = auto_follow_house_state
        self._lock_check_interval = lock_check_interval
        self._delegate_lights_to_nm = delegate_lights_to_nm

        # Observation mode: when True, entry evaluation and armed state
        # tracking continue, but no lock commands, NM alerts, or camera
        # triggers are executed.  Controlled via
        # switch.ura_security_observation_mode.
        self.observation_mode: bool = False

        # OC Phase 5 Pillar A handshake — unsub for SIGNAL_OPTIMIZER_INTENT
        # plus per-call veto-reason scratch. The unsub is stored separately
        # so async_setup can detect re-entry (Bug Class #50).
        self._optimizer_intent_unsub = None
        self._last_veto_reason: str | None = None

        # Runtime state
        self._active_alert = False
        self._alert_details: dict[str, Any] = {}
        self._last_entry_event: dict[str, Any] = {}
        self._lock_compliance: dict[str, str] = {}  # entity_id -> "locked"/"unlocked"
        # RESTART-SAFETY-DOCTRINE-1 F11: display-only diagnostic counters.
        # restart: RESET WITH REASON — no rate-cap consumer reads either
        # value; only sensor attribute payloads at 1759, 2448.
        self._alerts_today = DailyCounter(
            name="security.alerts_today",
            persist=False,
            reason="display-only alert count; not read on any policy path",
        )
        self._lock_checks_today = DailyCounter(
            name="security.lock_checks_today",
            persist=False,
            reason=(
                "display-only sweep count; the lock sweep runs on its own "
                "interval regardless of this value"
            ),
        )
        # Retained for backward-compat with any external inspector.
        self._last_reset_date: str = ""

        # Open entries tracking: entity_id -> opened_at timestamp
        self._open_entries: dict[str, datetime] = {}

        # Lock sweep results (persisted for sensor exposure)
        self._last_lock_sweep: dict[str, Any] = {}
        # NM Cycle A A3: per-entity unavailability dedup (unix ts of last emit).
        self._lock_unavailable_last_notified: dict[str, float] = {}

        # Sub-components
        self._sanction_checker = SanctionChecker(hass)
        self._entry_processor = EntryProcessor(hass, self._sanction_checker)
        self._camera_dispatcher = CameraRecordDispatcher(hass)
        self._pattern_learner = SecurityPatternLearner(hass)

        # Sync guard to prevent bidirectional alarm panel loops
        self._syncing_alarm_panel = False

        # Entry sensor debounce: entity_id -> last trigger timestamp
        self._entry_debounce: dict[str, datetime] = {}
        self._entry_debounce_seconds: int = 10

        # House-State Rung 2a (v5.39.0): auto-follow arming debounce state.
        # ``_pending_house_state`` holds the latest target house-state string
        # while ``_house_state_debounce_unsub`` is the async_call_later handle
        # scheduled to fire after ``SECURITY_AUTO_FOLLOW_ARM_DELAY_S`` seconds
        # of quiet. A newer intent cancels the pending handle and re-schedules,
        # so a rapid flap (AWAY→ARRIVING→HOME_DAY within seconds) collapses to
        # ONE net arming action against the LAST state.
        # ``_state_driven_arming_last`` is the per-coordinator execution
        # observability record (INV-1) surfaced on
        # ``sensor.ura_security_armed_state``.
        # A-L2 fix-up: typed Optional; None means "no pending fire".
        self._pending_house_state: str | None = None
        self._house_state_debounce_unsub = None
        self._state_driven_arming_last: dict[str, Any] = {}

        # A-H2 fix-up: manual-override hold. When the operator arms/disarms
        # via UI/service, we stamp the CURRENT house_state string here so a
        # subsequent auto-follow fire for the SAME house_state is suppressed
        # (``suppressed="manual_hold"``). The next distinct house-state
        # transition clears the stamp — manual wins for the remainder of
        # that house-state, auto-follow resumes on real state change.
        self._manual_action_house_state: str | None = None

        # B-M1 fix-up: teardown flag re-checked at fire time so a debounced
        # fire that lands DURING or AFTER async_teardown becomes a no-op.
        self._shutting_down: bool = False

    async def async_setup(self) -> None:
        """Set up the Security Coordinator."""
        _LOGGER.info(
            "Setting up Security Coordinator: %d locks, %d garage doors, "
            "%d entry sensors, %d lights, %d cameras, alarm_panel=%s, "
            "auto_follow=%s, camera_recording=%s, lock_check=%dm",
            len(self._lock_entities),
            len(self._garage_entities),
            len(self._entry_sensors),
            len(self._security_light_entities),
            len(self._camera_entities),
            self._alarm_panel_entity or "none",
            self._auto_follow_house_state,
            self._camera_recording_enabled,
            self._lock_check_interval,
        )

        # Entry sensor state listeners
        if self._entry_sensors:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    self._entry_sensors,
                    self._handle_entry_sensor_change,
                )
            )
            # Seed open entries from current state (handles HA restart)
            for sensor_id in self._entry_sensors:
                state = self.hass.states.get(sensor_id)
                if state and state.state in ("on", "open"):
                    self._open_entries[sensor_id] = dt_util.utcnow()

        # Alarm panel bidirectional sync
        if self._alarm_panel_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [self._alarm_panel_entity],
                    self._handle_alarm_panel_change,
                )
            )

        # Geofence arrival: watch person.* entities for not_home → home
        # Automatically adds arriving persons to expected arrivals list
        self._setup_geofence_listener()

        # Periodic lock check
        if self._lock_check_interval > 0 and (
            self._lock_entities or self._garage_entities
        ):
            self._unsub_listeners.append(
                async_track_time_interval(
                    self.hass,
                    self._handle_periodic_lock_check,
                    timedelta(minutes=self._lock_check_interval),
                )
            )

        # Camera platform detection
        if self._camera_recording_enabled and self._camera_entities:
            await self._camera_dispatcher.async_setup(self._camera_entities)

        # v3.22.0 D2: Subscribe to safety hazard signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SAFETY_HAZARD,
                self._handle_safety_hazard,
            )
        )

        # OC Phase 5 Pillar A: subscribe to SIGNAL_OPTIMIZER_INTENT so this
        # coordinator can veto any optimizer-proposed actuation on locks
        # / alarm panels. Bug Class #50 guardrail: stored unsub avoids
        # double-subscribe across an options-flow re-setup.
        if self._optimizer_intent_unsub is None:
            self._optimizer_intent_unsub = async_dispatcher_connect(
                self.hass,
                SIGNAL_OPTIMIZER_INTENT,
                self._on_optimizer_intent,
            )
            self._unsub_listeners.append(self._optimizer_intent_unsub)

        # v3.22.0 D3: Subscribe to person arriving signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PERSON_ARRIVING,
                self._handle_person_arriving_signal,
            )
        )

        # v5.37.0 (House-State Rung 1): subscribe to SIGNAL_HOUSE_STATE_CHANGED
        # so the existing arming map (_handle_house_state_intent) actually
        # fires — previously it waited for a "house_state_change" Intent that
        # nothing constructed. The signal handler queues an Intent through
        # the CoordinatorManager, so evaluate()'s existing gates apply:
        #   - _auto_follow_house_state flag (CONF_SECURITY_AUTO_FOLLOW,
        #     default False — const.py:1114)
        #   - observation_mode suppression (evaluate() line ~695)
        # Unsub tracked via _unsub_listeners (Bug Class #50).
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HOUSE_STATE_CHANGED,
                self._on_house_state_changed_signal,
            )
        )

        # Anomaly detection setup
        from .coordinator_diagnostics import AnomalyDetector
        from ..const import (  # noqa: PLC0415
            CONF_SECURITY_ANOMALY_SENSITIVITY,
            DEFAULT_ANOMALY_SENSITIVITY,
            ANOMALY_SENSITIVITY_MULTIPLIERS,
            CONF_ENTRY_TYPE,
            ENTRY_TYPE_COORDINATOR_MANAGER,
        )

        # v4.6.3 D10: Read sensitivity bucket from CM entry options.
        _security_sensitivity = DEFAULT_ANOMALY_SENSITIVITY
        try:
            for _ce in self.hass.config_entries.async_entries(DOMAIN):
                if _ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    _security_sensitivity = {**_ce.data, **_ce.options}.get(
                        CONF_SECURITY_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                    )
                    break
        except Exception:
            pass
        _security_sensitivity_mult = ANOMALY_SENSITIVITY_MULTIPLIERS.get(_security_sensitivity, 1.0)
        self.anomaly_detector = AnomalyDetector(
            self.hass, self.COORDINATOR_ID, SECURITY_METRICS,
            sensitivity_multiplier=_security_sensitivity_mult,
            # v4.6.5.3 surface fix
            suppressed_metric_names=SECURITY_SUPPRESSED_FROM_PERSISTENCE,
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception:
            _LOGGER.debug("Failed to load security anomaly baselines (non-fatal)")

        _LOGGER.info("Security Coordinator setup complete")

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Evaluate intents and return proposed actions."""
        actions: list[CoordinatorAction] = []
        self._maybe_reset_daily_counters()

        for intent in intents:
            if intent.source == "state_change" and intent.entity_id in self._entry_sensors:
                actions.extend(await self._handle_entry_intent(intent, context))
            elif intent.source == "census_update":
                actions.extend(self._handle_census_intent(intent, context))
            elif intent.source == "house_state_change" and self._auto_follow_house_state:
                actions.extend(self._handle_house_state_intent(intent))
            elif intent.source == "alarm_panel_change":
                self._handle_alarm_sync(intent)
            elif intent.source == "periodic_lock_check":
                actions.extend(await self._evaluate_lock_check())

        # v3.21.1 D1: Observation mode — entry evaluation and armed state
        # tracking run normally, but no actions are executed (lock commands,
        # NM alerts, camera triggers).
        if self.observation_mode and actions:
            _LOGGER.info(
                "[observation mode] Security would execute %d action(s) — suppressed: %s",
                len(actions),
                ", ".join(a.description for a in actions[:5]),
            )
            return []

        return actions

    def is_hazard_active(self, hazard_type: str, location: str) -> bool:
        """Check if a security hazard is still active (for NM re-fire logic)."""
        if hazard_type in ("intrusion", "entry_alert", "unknown_person"):
            return self._active_alert
        return False

    async def async_teardown(self) -> None:
        """Tear down the Security Coordinator."""
        # B-M1 fix-up: mark shutdown BEFORE cancelling listeners so a fire
        # that races past cancel returns immediately at the gate re-check.
        self._shutting_down = True
        self._cancel_listeners()
        # B-M1 / C-C7 fix-up: reset the optimizer-intent unsub handle so
        # re-setup after teardown re-subscribes cleanly. ``_cancel_listeners``
        # already fired the dispatcher unsub (handle was on
        # ``self._unsub_listeners``).
        self._optimizer_intent_unsub = None
        # House-State Rung 2a: cancel any pending debounced auto-follow
        # fire so a shutdown-time reload does not arm 30s after teardown.
        if self._house_state_debounce_unsub is not None:
            try:
                self._house_state_debounce_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._house_state_debounce_unsub = None
        self._pending_house_state = None
        if self.anomaly_detector is not None:
            try:
                await self.anomaly_detector.save_baselines()
            except Exception:
                _LOGGER.debug("Failed to save security anomaly baselines (non-fatal)")
        _LOGGER.info("Security Coordinator torn down")

    # =========================================================================
    # Intent handlers
    # =========================================================================

    async def _handle_entry_intent(
        self,
        intent: Intent,
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Handle an entry sensor state change intent.

        v4.6.5 D2: Made async to support save_anomaly_event persistence emit.

        METRIC AUDIT (v4.6.5 binary-metric check per v4.6.3.1 doctrine):
        - alert_trigger_frequency: recorded as a Severity score (LOW=1, MEDIUM=2,
          HIGH=3, CRITICAL=4). Continuous ordinal — not binary. Each entry event
          produces a real severity score value. Suitable for z-score. WIRE.
        - entry_anomaly_score: defined in SECURITY_METRICS but never recorded via
          record_observation (no call site exists). SUPPRESSED_FROM_PERSISTENCE —
          metric is silent; z-score detection never fires for it.
          Reference: v4.6.3.1 binary-metric doctrine — suppress silent metrics.
        """
        # v4.6.5.1 P2: SUPPRESSED_FROM_PERSISTENCE was promoted to module-level
        # constant `SECURITY_SUPPRESSED_FROM_PERSISTENCE` at the top of this
        # file so the parametric meta-test can introspect it. See that
        # constant's docstring for the per-metric suppression rationale.
        event = EntryEvent(
            entity_id=intent.entity_id,
            new_state=intent.data.get("new_state", "on"),
            old_state=intent.data.get("old_state", "off"),
        )

        # Track open/close for open entries sensor
        if event.new_state in ("on", "open"):
            self._open_entries[intent.entity_id] = dt_util.utcnow()
        elif event.new_state in ("off", "closed", "unavailable", "unknown"):
            if intent.entity_id in self._open_entries:
                self._open_entries.pop(intent.entity_id)
                async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

        # Only process door/window opening (off->on or closed->open)
        if event.new_state not in ("on", "open"):
            return []

        # Debounce: skip if same sensor fired within cooldown window
        now = dt_util.utcnow()
        last_trigger = self._entry_debounce.get(intent.entity_id)
        if last_trigger and (now - last_trigger).total_seconds() < self._entry_debounce_seconds:
            _LOGGER.debug("Entry debounced: %s (%.1fs since last)", intent.entity_id,
                          (now - last_trigger).total_seconds())
            return []
        self._entry_debounce[intent.entity_id] = now

        # Record for pattern learning
        self._pattern_learner.record_entry(intent.entity_id)

        verdict = self._entry_processor.evaluate_entry(
            event, self._armed_state, context
        )

        # Update last entry event
        self._last_entry_event = {
            "entity_id": intent.entity_id,
            "verdict": verdict.value,
            "armed_state": self._armed_state.value,
            "timestamp": dt_util.utcnow().isoformat(),
        }

        # Record anomaly observation and persist if anomaly detected
        if self.anomaly_detector is not None:
            severity_score = _VERDICT_SEVERITY.get(verdict, Severity.LOW).value
            anomaly = self.anomaly_detector.record_observation(
                "alert_trigger_frequency", "house", float(severity_score)
            )
            if anomaly:
                try:
                    from .anomaly_event import (  # noqa: PLC0415
                        AnomalyEvent,
                        AnomalySeverity as _NewSev,
                        AnomalyType,
                        build_context_json,
                        map_diag_severity,
                    )
                    _ctx = build_context_json(
                        source_signal="entry_sensor_state_change",
                        extra={
                            "entity_id": intent.entity_id,
                            "verdict": verdict.value,
                        },
                    )
                    _event = AnomalyEvent(
                        coordinator="security",
                        type="security.alert_trigger_frequency",
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
                        "Security alert_trigger_frequency anomaly persisted: "
                        "entity=%s verdict=%s z=%.2f",
                        intent.entity_id, verdict.value, anomaly.z_score,
                    )
                    _activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                    if _activity_logger:
                        await _activity_logger.log(
                            coordinator="security",
                            action="anomaly",
                            description=(
                                f"Security alert_trigger_frequency anomaly: "
                                f"verdict={verdict.value} z={anomaly.z_score:.2f}"
                            ),
                            importance="notable",
                            details={
                                "type": "security.alert_trigger_frequency",
                                "z_score": round(anomaly.z_score, 3),
                                "verdict": verdict.value,
                                "entity_id": intent.entity_id,
                            },
                        )
                except Exception:
                    _LOGGER.debug(
                        "Security alert_trigger_frequency anomaly persist failed",
                        exc_info=True,
                    )

        actions = self._verdict_to_actions(verdict, intent.entity_id)

        # Fire entity update signal
        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

        return actions

    def _handle_census_intent(
        self,
        intent: Intent,
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Handle census update — check for unknown persons (req #7)."""
        if not self._sanction_checker.has_unknown_persons(context):
            return []

        # v3.21.2: Gate side effects by observation mode (review fix R1-F2)
        if self.observation_mode:
            _LOGGER.info(
                "[observation mode] Security would alert on unknown person — suppressed"
            )
            return []

        _LOGGER.warning("Unknown person detected — locking all doors")
        self._active_alert = True
        self._alert_details = {
            "type": "unknown_person",
            "timestamp": dt_util.utcnow().isoformat(),
        }
        self._alerts_today.increment()

        # v3.12.0 M2: Dispatch security event signal for automation chaining
        async_dispatcher_send(
            self.hass,
            SIGNAL_SECURITY_EVENT,
            SecurityEventPayload(
                event_type="unknown_person",
                severity="high",
                details="Unknown person detected on property",
            ),
        )

        actions = self._generate_lockdown_actions("Unknown person detected on property")

        # Camera trigger if enabled (uses platform-aware dispatcher)
        if self._camera_recording_enabled and self._camera_entities:
            actions.extend(
                self._camera_dispatcher._build_camera_actions(
                    self._camera_entities, self._camera_record_duration
                )
            )

        # Light handling: delegate to NM or direct control
        if self._delegate_lights_to_nm:
            actions.append(
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.HIGH,
                    message="Unknown person detected — all doors locked",
                    channels=["security"],
                    hazard_type="intruder",
                    location="property",
                    description="Unknown person alert notification",
                )
            )
        else:
            actions.extend(
                self._build_security_light_actions(
                    Severity.HIGH, "Unknown person — security lights"
                )
            )
            actions.append(
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.HIGH,
                    message="Unknown person detected — all doors locked",
                    channels=["security"],
                    description="Unknown person alert notification",
                )
            )

        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)
        return actions

    @callback
    def _on_house_state_changed_signal(self, payload: Any) -> None:
        """Bridge SIGNAL_HOUSE_STATE_CHANGED into the coordinator intent queue.

        v5.37.0 (House-State Rung 1): the arming map at
        ``_handle_house_state_intent`` waited for a "house_state_change"
        Intent that no producer ever built. Presence dispatches the signal
        directly (presence.py:~5569) with a dict payload
        ``{"old_state", "new_state", "trigger", "confidence"}``. Queue an
        Intent through the CoordinatorManager so the existing evaluate()
        gates (flag + observation_mode) apply uniformly.

        Behavior when the flag is off: evaluate() short-circuits at
        ``self._auto_follow_house_state`` (line ~685) before the arming map
        runs, so no ArmedState mutation and no actions are produced.
        """
        try:
            # Flag-off short circuit — avoid even queueing to keep the
            # no-op path byte-cheap and observable.
            if not self._auto_follow_house_state:
                return
            new_state = ""
            if isinstance(payload, dict):
                new_state = str(payload.get("new_state", "") or "")
            else:
                new_state = str(getattr(payload, "new_state", "") or "")
            if not new_state:
                return
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return
            _LOGGER.info(
                "Security: queueing house_state_change intent (new_state=%s)",
                new_state,
            )
            manager.queue_intent(
                Intent(
                    source="house_state_change",
                    data={"new_state": new_state},
                    coordinator_id=self.COORDINATOR_ID,
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Security: house_state_changed signal handling failed",
                exc_info=True,
            )

    def _handle_house_state_intent(
        self,
        intent: Intent,
    ) -> list[CoordinatorAction]:
        """Rung 2a: schedule a debounced state-driven arming fire.

        The mapping (``_HOUSE_STATE_TO_ARMED``) is unchanged from Rung 1 —
        away→ARMED_AWAY, home_*/sleep/guest→ARMED_HOME, vacation→
        ARMED_VACATION, arriving/waking→DISARMED. Rather than mutate
        ``_armed_state`` synchronously (Rung 1 behavior) we now:

        1. Compute the target and short-circuit on unknown/no-op.
        2. Cancel any prior pending fire and replace ``_pending_house_state``
           with this newer target.
        3. Schedule ``_fire_state_driven_arming`` via ``async_call_later``
           after ``SECURITY_AUTO_FOLLOW_ARM_DELAY_S`` seconds of quiet.

        A rapid flap (AWAY→ARRIVING→HOME_DAY inside the debounce window)
        collapses to one net arming call against the LAST state.

        The evaluate() gate already ensures this handler only runs when
        ``self._auto_follow_house_state`` is True AND the coordinator is
        enabled (manager filters disabled coordinators before evaluate).
        Observation-mode is honored at fire time, NOT here — we still want
        the diagnostic attr to record a "would-arm" trace under observation.

        Returns [] unconditionally: the fire is out-of-band via
        ``handle_arm``/``handle_disarm`` (the SAME public entrypoints manual
        UI arming uses — INV-2 no-bypass). NM emit is via the CM's
        NotificationManager (INV-4). This deliberately bypasses the intent
        action pipeline because the debounced fire happens LATER than any
        current batch could tolerate.
        """
        new_house_state = str(intent.data.get("new_state", "") or "")
        new_armed = _HOUSE_STATE_TO_ARMED.get(new_house_state)
        if new_armed is None:
            # A-H3 fix-up: unmapped house_state (home_*, sleep) → no-op.
            return []

        # B-M2 / A-L1 fix-up: same-target short-circuit — target already
        # matches current armed state. If a prior fire is pending against
        # ANY target that would resolve to the same current armed, cancel
        # it (no reschedule, no noop churn).
        if new_armed == self._armed_state:
            if self._house_state_debounce_unsub is not None:
                try:
                    self._house_state_debounce_unsub()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "Security: same-target cancel failed", exc_info=True
                    )
                self._house_state_debounce_unsub = None
                self._pending_house_state = None
            return []

        # Cancel any prior pending fire; latest intent wins.
        if self._house_state_debounce_unsub is not None:
            try:
                self._house_state_debounce_unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Security: prior debounce cancel failed", exc_info=True
                )
            self._house_state_debounce_unsub = None

        self._pending_house_state = new_house_state

        # A-M1 fix-up: asymmetric debounce. Anti-flap protects ESCALATION
        # (avoid alarm-panel thrash); DE-ESCALATION (→ DISARMED targets
        # arriving/waking) is time-critical (operator at the door) so we
        # fire immediately via a 0-delay async_call_later — same code
        # path, but no user-facing wait.
        delay_s = (
            0.0
            if new_armed == ArmedState.DISARMED
            else float(SECURITY_AUTO_FOLLOW_ARM_DELAY_S)
        )
        _LOGGER.debug(
            "Security auto-follow: scheduled arming fire in %.1fs (target=%s "
            "from house_state=%s, current=%s)",
            delay_s,
            new_armed.value,
            new_house_state,
            self._armed_state.value,
        )
        self._house_state_debounce_unsub = async_call_later(
            self.hass,
            delay_s,
            self._fire_state_driven_arming,
        )
        return []

    async def _fire_state_driven_arming(self, _now: Any = None) -> None:
        """Execute the debounced state-driven arming (Rung 2a fire path).

        Called by ``async_call_later`` ``SECURITY_AUTO_FOLLOW_ARM_DELAY_S``
        seconds after the last house-state intent. Reads
        ``_pending_house_state`` (the LATEST target), resolves the armed
        target, and either:

        * suppresses under ``observation_mode`` (records "would-arm" in
          ``_state_driven_arming_last`` with ``suppressed="observation_mode"``,
          ``notified=False``); or
        * routes through the SAME public path manual UI arming uses:
          ``handle_arm(target.value)`` or ``handle_disarm()``. Those methods
          own the ``_armed_state`` mutation, alarm-panel sync, and the
          ``SIGNAL_SECURITY_ENTITIES_UPDATE`` dispatch.

        NM notification (INV-4) is emitted via the CM NotificationManager
        with severity per ``_STATE_DRIVEN_NM_SEVERITY`` and channel
        ``security``. If NM is unavailable, arming still proceeds but the
        diagnostic records ``notified=False``.
        """
        self._house_state_debounce_unsub = None
        target_state = self._pending_house_state
        self._pending_house_state = None
        if not target_state:
            return

        new_armed = _HOUSE_STATE_TO_ARMED.get(target_state)
        if new_armed is None:
            return

        old_state = self._armed_state
        now_iso = dt_util.utcnow().isoformat()
        base_record: dict[str, Any] = {
            "from_state": old_state.value,
            "to_armed": new_armed.value,
            "house_state": target_state,
            "at": now_iso,
        }

        def _record_suppressed(reason: str, *, dispatch: bool = True) -> None:
            record = {**base_record, "notified": False, "suppressed": reason}
            self._state_driven_arming_last = record
            if dispatch:
                async_dispatcher_send(
                    self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE
                )
            self._publish_policy_action(record)

        # A-H1 / C-1 fix-up: re-check gates at FIRE TIME (they can flip
        # during the debounce window). Order: shutting_down > enabled >
        # auto_follow_house_state > observation_mode. Each records the
        # suppression + dispatches the entities-update signal (so the
        # diagnostic sensor observes the "would-fire" trace).
        if self._shutting_down:
            # Do NOT record; teardown may have torn down manager/sensors.
            _LOGGER.debug(
                "Security auto-follow: fire skipped — shutting_down"
            )
            return
        if not self._enabled:
            _record_suppressed("disabled")
            _LOGGER.info(
                "Security auto-follow: fire skipped — coordinator disabled"
            )
            return
        if not self._auto_follow_house_state:
            _record_suppressed("auto_follow_off")
            _LOGGER.info(
                "Security auto-follow: fire skipped — flag turned off "
                "during debounce"
            )
            return

        # A-H2 fix-up: manual override hold. If the operator arm/disarmed
        # UNDER THE SAME house_state (stamp matches target_state), suppress
        # the auto-follow fire. The next distinct house-state transition
        # clears the stamp so auto-follow resumes.
        if (
            self._manual_action_house_state is not None
            and self._manual_action_house_state == target_state
        ):
            _record_suppressed("manual_hold")
            _LOGGER.info(
                "Security auto-follow: fire suppressed — manual action holds "
                "for house_state=%s (target=%s)",
                target_state,
                new_armed.value,
            )
            return
        if (
            self._manual_action_house_state is not None
            and self._manual_action_house_state != target_state
        ):
            _LOGGER.debug(
                "Security auto-follow: manual-hold cleared (was %s, now %s)",
                self._manual_action_house_state,
                target_state,
            )
            self._manual_action_house_state = None

        # Observation mode: NO actuation, NO NM — but record the "would".
        if self.observation_mode:
            _record_suppressed("observation_mode")
            _LOGGER.info(
                "[observation mode] Security auto-follow would arm %s → %s "
                "(house=%s) — suppressed",
                old_state.value,
                new_armed.value,
                target_state,
            )
            return

        # Same-state no-op after the debounce window (e.g. flap resolved
        # back to current). Still refresh the diagnostic for observability.
        if new_armed == old_state:
            _record_suppressed("noop")
            return

        _LOGGER.info(
            "Security auto-follow: house_state=%s → arming %s (was %s)",
            target_state,
            new_armed.value,
            old_state.value,
        )

        # Route through the SAME public path manual UI arming uses (INV-2).
        # ``source="auto_follow"`` suppresses the manual-hold stamp so the
        # fire path never latches itself out.
        try:
            if new_armed == ArmedState.DISARMED:
                await self.handle_disarm(source="auto_follow")
            else:
                await self.handle_arm(new_armed.value, source="auto_follow")
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Security auto-follow: arming call failed for target=%s",
                new_armed.value,
            )
            # A-M2 / C-4 fix-up: failure branch dispatches the entities-
            # update signal (same as observation/noop branches) so the
            # diagnostic sensor reflects the arm_call_failed record.
            _record_suppressed("arm_call_failed")
            return

        # NM notification (INV-4) — direction-aware severity (A-M3 fix-up):
        # HIGH on escalation (stricter posture), MEDIUM on de-escalation.
        # NM lookup uses the PUBLIC hass.data slot (B-H1 fix-up), never
        # the private manager attribute.
        severity = _state_driven_severity(old_state, new_armed)
        notified = False
        try:
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is not None:
                await nm.async_notify(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=severity,
                    title="Security auto-follow",
                    message=(
                        f"House state {target_state} → armed {new_armed.value}"
                    ),
                    hazard_type="security_state_change",
                    location="house",
                )
                notified = True
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Security auto-follow: NM notify failed (non-fatal)",
                exc_info=True,
            )

        record = {**base_record, "notified": notified, "suppressed": None}
        self._state_driven_arming_last = record

        # Activity log parity with Rung 1.
        activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
        if activity_logger:
            self.hass.async_create_task(
                activity_logger.log(
                    coordinator="security",
                    action="armed_state_change",
                    description=(
                        f"Armed state {old_state.value} -> {new_armed.value} "
                        f"(house={target_state}, auto_follow)"
                    ),
                    importance="notable",
                    details={
                        "old_state": old_state.value,
                        "new_state": new_armed.value,
                        "house_state": target_state,
                        "source": "auto_follow",
                    },
                )
            )

        if self.decision_logger is not None:
            from .coordinator_diagnostics import DecisionLog  # noqa: PLC0415

            self.decision_logger.log_decision(
                DecisionLog(
                    coordinator_id=self.COORDINATOR_ID,
                    decision_type="armed_state_change",
                    context=f"auto_follow: {target_state}",
                    action=f"{old_state.value} → {new_armed.value}",
                )
            )

        self._publish_policy_action(record)

    def _publish_policy_action(self, record: dict[str, Any]) -> None:
        """Publish this state-driven action to the CM house-policy surface.

        INV-1: the ``sensor.ura_coordinator_manager_house_policy`` diagnostic
        surfaces active policies + last state-driven action across all
        coordinators. Best-effort — a failure here MUST NOT block arming.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return
            record_fn = getattr(manager, "record_state_driven_action", None)
            if record_fn is None:
                return
            record_fn(
                policy="security.auto_follow",
                coordinator=self.COORDINATOR_ID,
                action_record=record,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Security: publish_policy_action failed (non-fatal)",
                exc_info=True,
            )

    def _handle_alarm_sync(self, intent: Intent) -> None:
        """Bidirectional sync from alarm panel state change (req #4)."""
        if self._syncing_alarm_panel:
            return

        new_panel_state = intent.data.get("new_state", "")
        mapped = _ALARM_STATE_MAP.get(new_panel_state)
        if mapped is None or mapped == self._armed_state:
            return

        old_state = self._armed_state
        self._armed_state = mapped
        _LOGGER.info(
            "Alarm panel sync: panel=%s → armed=%s (was %s)",
            new_panel_state,
            mapped.value,
            old_state.value,
        )
        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

    # =========================================================================
    # Action generation helpers
    # =========================================================================

    def _verdict_to_actions(
        self,
        verdict: EntryVerdict,
        entity_id: str,
    ) -> list[CoordinatorAction]:
        """Convert an entry verdict to coordinator actions."""
        if verdict in (EntryVerdict.SANCTIONED, EntryVerdict.LOG_ONLY):
            return [
                CoordinatorAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.LOW,
                    description=f"Entry {verdict.value}: {entity_id}",
                )
            ]

        if verdict == EntryVerdict.NOTIFY:
            return [
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.LOW,
                    message=f"Entry noted at {entity_id} — known person, unusual timing",
                    channels=["security"],
                    description=f"Entry notify: {entity_id}",
                )
            ]

        if verdict == EntryVerdict.INVESTIGATE:
            actions: list[CoordinatorAction] = []
            if self._delegate_lights_to_nm:
                actions.append(
                    NotificationAction(
                        coordinator_id=self.COORDINATOR_ID,
                        severity=Severity.MEDIUM,
                        message=f"Investigate entry at {entity_id} — armed, unrecognized",
                        channels=["security"],
                        hazard_type="investigate",
                        location=entity_id,
                        description=f"Entry investigate: {entity_id}",
                    )
                )
            else:
                actions.extend(
                    self._build_security_light_actions(
                        Severity.MEDIUM, f"Investigate lights ({entity_id})"
                    )
                )
                actions.append(
                    NotificationAction(
                        coordinator_id=self.COORDINATOR_ID,
                        severity=Severity.MEDIUM,
                        message=f"Investigate entry at {entity_id} — armed, unrecognized",
                        channels=["security"],
                        description=f"Entry investigate: {entity_id}",
                    )
                )
            return actions

        # ALERT or ALERT_HIGH
        # v3.21.2: Gate side effects by observation mode (review fix R1-F2)
        if self.observation_mode:
            _LOGGER.info(
                "[observation mode] Security would alert on entry at %s (%s) — suppressed",
                entity_id, verdict.value,
            )
            return []

        self._active_alert = True
        self._alert_details = {
            "type": "entry_alert",
            "entity_id": entity_id,
            "verdict": verdict.value,
            "timestamp": dt_util.utcnow().isoformat(),
        }
        self._alerts_today.increment()

        sev_str = "critical" if verdict == EntryVerdict.ALERT_HIGH else "high"
        # v3.12.0 M2: Dispatch security event signal for automation chaining
        async_dispatcher_send(
            self.hass,
            SIGNAL_SECURITY_EVENT,
            SecurityEventPayload(
                event_type="entry_alert",
                severity=sev_str,
                source_entity=entity_id,
                details=f"Security alert at {entity_id} — {verdict.value}",
            ),
        )

        severity = (
            Severity.CRITICAL if verdict == EntryVerdict.ALERT_HIGH else Severity.HIGH
        )
        actions: list[CoordinatorAction] = []

        # Lock all doors
        actions.extend(
            self._generate_lockdown_actions(f"Security alert at {entity_id}")
        )

        # Camera recording trigger (uses platform-aware dispatcher)
        if self._camera_recording_enabled and self._camera_entities:
            actions.extend(
                self._camera_dispatcher._build_camera_actions(
                    self._camera_entities, self._camera_record_duration
                )
            )

        # Light handling: delegate to NM (via hazard_type) or direct control
        if self._delegate_lights_to_nm:
            hazard = "intruder" if verdict == EntryVerdict.ALERT_HIGH else "investigate"
            actions.append(
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=severity,
                    message=f"Security {verdict.value}: entry at {entity_id}",
                    channels=["security"],
                    hazard_type=hazard,
                    location=entity_id,
                    description=f"Security alert notification: {entity_id}",
                )
            )
        else:
            actions.extend(
                self._build_security_light_actions(
                    severity, f"Security alert lights ({verdict.value})"
                )
            )
            actions.append(
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=severity,
                    message=f"Security {verdict.value}: entry at {entity_id}",
                    channels=["security"],
                    description=f"Security alert notification: {entity_id}",
                )
            )

        return actions

    def _build_security_light_actions(
        self, severity: Severity, description: str
    ) -> list[ServiceCallAction]:
        """Generate direct ServiceCallActions for security lights (NM bypass)."""
        actions: list[ServiceCallAction] = []
        for light_id in self._security_light_entities:
            actions.append(
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    target_device=light_id,
                    severity=severity,
                    service="light.turn_on",
                    service_data={
                        "entity_id": light_id,
                        "flash": "long",
                    },
                    description=f"{description}: {light_id}",
                )
            )
        return actions

    def _generate_lockdown_actions(
        self, reason: str
    ) -> list[ServiceCallAction]:
        """Generate actions to lock all doors and close garage doors."""
        actions: list[ServiceCallAction] = []

        for lock_id in self._lock_entities:
            actions.append(
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    target_device=lock_id,
                    severity=Severity.HIGH,
                    service="lock.lock",
                    service_data={"entity_id": lock_id},
                    description=f"Lock door ({reason}): {lock_id}",
                )
            )

        for garage_id in self._garage_entities:
            actions.append(
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    target_device=garage_id,
                    severity=Severity.HIGH,
                    service="cover.close_cover",
                    service_data={"entity_id": garage_id},
                    description=f"Close garage ({reason}): {garage_id}",
                )
            )

        return actions

    # =========================================================================
    # Periodic lock check (req #8 — armed-independent)
    # =========================================================================

    async def _evaluate_lock_check(self) -> list[CoordinatorAction]:
        """Check all locks and garage doors, lock any that are unlocked."""
        self._lock_checks_today.increment()
        actions: list[CoordinatorAction] = []
        unlocked: list[str] = []
        unavailable: list[str] = []

        for lock_id in self._lock_entities:
            state = self.hass.states.get(lock_id)
            if state is None or state.state in ("unavailable", "unknown"):
                unavailable.append(lock_id)
                self._lock_compliance[lock_id] = "unavailable"
                continue
            self._lock_compliance[lock_id] = state.state
            if state.state == "unlocked":
                unlocked.append(lock_id)
                actions.append(
                    ServiceCallAction(
                        coordinator_id=self.COORDINATOR_ID,
                        target_device=lock_id,
                        severity=Severity.MEDIUM,
                        service="lock.lock",
                        service_data={"entity_id": lock_id},
                        description=f"Periodic lock check: locking {lock_id}",
                    )
                )

        for garage_id in self._garage_entities:
            state = self.hass.states.get(garage_id)
            if state is None or state.state in ("unavailable", "unknown"):
                unavailable.append(garage_id)
                self._lock_compliance[garage_id] = "unavailable"
                continue
            self._lock_compliance[garage_id] = state.state
            if state.state == "open":
                unlocked.append(garage_id)
                actions.append(
                    ServiceCallAction(
                        coordinator_id=self.COORDINATOR_ID,
                        target_device=garage_id,
                        severity=Severity.MEDIUM,
                        service="cover.close_cover",
                        service_data={"entity_id": garage_id},
                        description=f"Periodic lock check: closing {garage_id}",
                    )
                )

        if unavailable:
            _LOGGER.warning(
                "Periodic lock check: %d device(s) unavailable: %s",
                len(unavailable),
                ", ".join(unavailable),
            )
            # NM Cycle A A3: per-entity dedup (default 1/day/lock). An
            # entity is included in the notification payload only if it
            # hasn't been notified within the dedup window; the full list
            # remains in _last_lock_sweep["unavailable"] for dashboards.
            from ..const import (
                CONF_LOCK_UNAVAILABLE_DEDUP_S,
                DEFAULT_LOCK_UNAVAILABLE_DEDUP_S,
            )
            from ._nm_cycle_a import nm_cycle_a_knob
            import time as _time
            dedup_s = nm_cycle_a_knob(
                self.hass,
                CONF_LOCK_UNAVAILABLE_DEDUP_S,
                DEFAULT_LOCK_UNAVAILABLE_DEDUP_S,
            )
            now_ts = _time.time()
            to_notify: list[str] = []
            for eid in unavailable:
                last = self._lock_unavailable_last_notified.get(eid, 0.0)
                if dedup_s <= 0 or (now_ts - last) >= dedup_s:
                    to_notify.append(eid)
                    self._lock_unavailable_last_notified[eid] = now_ts
            if to_notify:
                actions.append(
                    NotificationAction(
                        coordinator_id=self.COORDINATOR_ID,
                        severity=Severity.MEDIUM,
                        message=(
                            f"Lock check: {len(to_notify)} device(s) offline: "
                            f"{', '.join(to_notify)}"
                        ),
                        channels=["security"],
                        description="Lock check unavailable device notification",
                    )
                )
            else:
                _LOGGER.info(
                    "Lock-unavailable NM suppressed by A3 dedup "
                    "(%d entities within %ds window)",
                    len(unavailable), int(dedup_s),
                )

        if unlocked:
            _LOGGER.info(
                "Periodic lock check: %d unlocked, locking: %s",
                len(unlocked),
                ", ".join(unlocked),
            )
            actions.append(
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    message=f"Lock check: locked {len(unlocked)} door(s): {', '.join(unlocked)}",
                    channels=["security"],
                    description="Periodic lock check notification",
                )
            )

        # Persist sweep results for sensor exposure BEFORE compliance tracking
        # so sweep data is always saved even if compliance tracking fails.
        # Note: "lock_actions_sent" are proposed actions; actual execution
        # depends on CoordinatorManager conflict resolution.
        self._last_lock_sweep = {
            "timestamp": dt_util.utcnow().isoformat(),
            "found_unlocked": unlocked,
            "lock_actions_sent": unlocked.copy(),
            "unavailable": unavailable,
            "checks_today": self._lock_checks_today.value,
        }

        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

        # Compliance tracking (non-critical — don't let failures crash the sweep)
        if unlocked and self.compliance_tracker is not None:
            for entity_id in unlocked:
                try:
                    await self.compliance_tracker.schedule_check(
                        decision_id=0,
                        scope=self.COORDINATOR_ID,
                        device_type="lock",
                        device_id=entity_id,
                        commanded_state={"state": "locked"},
                    )
                except Exception:
                    # v4.5.20: was debug. Lock action still queues; only
                    # the audit/compliance trail is at risk. Soft escalate
                    # with exc_info for observability.
                    _LOGGER.warning(
                        "Compliance check scheduling failed for %s "
                        "(non-fatal — lock action still queued)",
                        entity_id,
                        exc_info=True,
                    )

        return actions

    # =========================================================================
    # OC Phase 5 Pillar A — sibling-coordinator handshake
    # =========================================================================

    @callback
    def _on_optimizer_intent(self, intent: dict) -> None:
        """Dispatcher callback for SIGNAL_OPTIMIZER_INTENT.

        Evaluates ``honor_optimizer_intent`` and fires
        ``SIGNAL_OPTIMIZER_INTENT_VETO`` when this coordinator refuses.
        Defensive — never raises into the broker.
        """
        try:
            if not isinstance(intent, dict):
                return
            # B-H1 fix-up: L1 inertness — see Energy._on_optimizer_intent
            # for the full rationale.
            eff = intent.get("effective_level")
            if eff in ("advisory", "shadow"):
                _LOGGER.debug(
                    "Security: skipping intent honor at L1 "
                    "effective_level=%s (action_id=%s target=%s)",
                    eff,
                    intent.get("action_id"),
                    intent.get("target_entity"),
                )
                return
            if self.honor_optimizer_intent(intent):
                return
            action_id = intent.get("action_id")
            if not action_id:
                return
            async_dispatcher_send(
                self.hass,
                SIGNAL_OPTIMIZER_INTENT_VETO,
                {
                    "action_id": action_id,
                    "vetoed_by": "security",
                    "reason": self._last_veto_reason or "security_policy",
                },
            )
            _LOGGER.info(
                "Optimizer intent vetoed by Security (action_id=%s "
                "reason=%s target=%s)",
                action_id,
                self._last_veto_reason,
                intent.get("target_entity"),
            )
        except Exception:  # noqa: BLE001 — never crash sibling on broker intent
            _LOGGER.debug(
                "Security._on_optimizer_intent raised", exc_info=True,
            )

    def honor_optimizer_intent(self, intent: dict) -> bool:
        """Return True to ACK (allow), False to VETO an Optimizer intent.

        Default vetoes (Phase 1 — zero allowlist):
            * ``self.observation_mode`` is True — veto everything.
            * Target entity is in the ``lock.*`` domain — always veto.
            * Target entity is in the ``alarm_control_panel.*`` domain —
              always veto.

        Read-only — never mutates state, never raises.
        """
        self._last_veto_reason = None

        try:
            target = (intent.get("target_entity") or "").strip()
        except Exception:  # noqa: BLE001
            return True
        if not target:
            return True

        if self.observation_mode:
            self._last_veto_reason = "observation_mode"
            return False

        if target.startswith("lock."):
            self._last_veto_reason = "lock_domain"
            return False

        if target.startswith("alarm_control_panel."):
            self._last_veto_reason = "alarm_panel_domain"
            return False

        return True

    # =========================================================================
    # State listener callbacks
    # =========================================================================

    @callback
    def _handle_entry_sensor_change(self, event: Event) -> None:
        """Handle entry sensor state change → queue intent."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        from .manager import CoordinatorManager

        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        manager.queue_intent(
            Intent(
                source="state_change",
                entity_id=entity_id,
                data={
                    "new_state": new_state.state if new_state else "",
                    "old_state": old_state.state if old_state else "",
                },
                coordinator_id=self.COORDINATOR_ID,
            )
        )

    @callback
    def _handle_alarm_panel_change(self, event: Event) -> None:
        """Handle alarm panel state change → queue intent."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        manager.queue_intent(
            Intent(
                source="alarm_panel_change",
                entity_id=self._alarm_panel_entity or "",
                data={
                    "new_state": new_state.state if new_state else "",
                    "old_state": old_state.state if old_state else "",
                },
                coordinator_id=self.COORDINATOR_ID,
            )
        )

    @callback
    def _handle_periodic_lock_check(self, _now: Any = None) -> None:
        """Handle periodic lock check timer → queue intent."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        manager.queue_intent(
            Intent(
                source="periodic_lock_check",
                coordinator_id=self.COORDINATOR_ID,
            )
        )

    # =========================================================================
    # Geofence arrival listener
    # =========================================================================

    def _setup_geofence_listener(self) -> None:
        """Subscribe to person.* entities for arrival detection."""
        person_entities = [
            state.entity_id
            for state in self.hass.states.async_all("person")
        ]
        if not person_entities:
            _LOGGER.debug("No person entities found for geofence arrival detection")
            return

        _LOGGER.info(
            "Geofence arrival listener: watching %d person entities",
            len(person_entities),
        )
        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass,
                person_entities,
                self._handle_person_state_change,
            )
        )

    @callback
    def _handle_person_state_change(self, event: Event) -> None:
        """Auto-add expected arrival when person transitions toward home.

        Only active when armed — no need to track arrivals when disarmed.
        """
        if self._armed_state == ArmedState.DISARMED:
            return

        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None or old_state is None:
            return

        entity_id = event.data.get("entity_id", "")
        old_val = old_state.state
        new_val = new_state.state

        # not_home → home: person just arrived
        if old_val == "not_home" and new_val == "home":
            _LOGGER.info(
                "Geofence arrival: %s arrived home, adding to expected arrivals",
                entity_id,
            )
            self._sanction_checker.add_expected_arrival(entity_id, window_minutes=10)
            async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

        # not_home → zone (approaching): could be a nearby zone
        elif old_val == "not_home" and new_val not in ("not_home", "home", "unavailable", "unknown"):
            _LOGGER.info(
                "Geofence proximity: %s entered zone '%s', adding to expected arrivals",
                entity_id,
                new_val,
            )
            self._sanction_checker.add_expected_arrival(entity_id, window_minutes=30)
            async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

    # =========================================================================
    # v3.22.0 D2/D3: Cross-coordinator signal handlers
    # =========================================================================

    @callback
    def _handle_safety_hazard(self, hazard: Any) -> None:
        """Handle safety hazard signal — unlock egress doors on smoke/fire/CO.

        v3.22.0 D2: Cross-coordinator response to SIGNAL_SAFETY_HAZARD.
        Gated by CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS config toggle.
        """
        if not self._enabled:
            return
        if self.observation_mode:
            _LOGGER.debug("Security: Safety hazard received — suppressed by observation mode")
            return

        # Extract hazard fields with safe defaults
        if hazard is None:
            return
        if isinstance(hazard, dict):
            hazard_type = hazard.get("hazard_type", "")
            severity = hazard.get("severity", "")
        elif hasattr(hazard, "hazard_type"):
            hazard_type = getattr(hazard, "hazard_type", "")
            severity = getattr(hazard, "severity", "")
        else:
            return

        from ..const import CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS

        # Unlock all entry doors on smoke/fire/CO critical
        if hazard_type in ("smoke", "fire", "carbon_monoxide") and severity == "critical":
            if self._get_signal_config(CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS):
                _LOGGER.warning(
                    "Security: Safety hazard %s/%s — unlocking all egress doors",
                    hazard_type, severity,
                )
                for lock_id in self._lock_entities:
                    try:
                        self.hass.async_create_task(
                            self.hass.services.async_call(
                                "lock", "unlock",
                                {"entity_id": lock_id}, blocking=False,
                            )
                        )
                        # Review fix F5: log "requested" not "unlocked" (async task, not confirmed)
                        _LOGGER.info("Security: Requested unlock %s (safety egress)", lock_id)
                    except Exception:  # noqa: BLE001
                        _LOGGER.warning(
                            "Security: Failed to unlock %s (safety egress)", lock_id
                        )
                async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)
            else:
                _LOGGER.info(
                    "Security: Safety hazard %s/%s — would unlock egress doors "
                    "(disabled by config)",
                    hazard_type, severity,
                )

    @callback
    def _handle_person_arriving_signal(self, payload: Any) -> None:
        """Handle person arriving signal — add to expected arrivals.

        v3.22.0 D3: Cross-coordinator response to SIGNAL_PERSON_ARRIVING.
        Gated by CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED config toggle.
        """
        if not self._enabled:
            return
        if self.observation_mode:
            _LOGGER.debug("Security: Person arriving received — suppressed by observation mode")
            return

        if payload is None:
            return
        if isinstance(payload, dict):
            person_entity = payload.get("person_entity", "")
        elif hasattr(payload, "person_entity"):
            person_entity = getattr(payload, "person_entity", "")
        else:
            return

        if not person_entity:
            return

        from ..const import CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED

        if self._get_signal_config(CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED):
            _LOGGER.info(
                "Security: Person arriving %s — adding to expected arrivals",
                person_entity,
            )
            self._sanction_checker.add_expected_arrival(
                person_entity, window_minutes=5
            )
            async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)
        else:
            _LOGGER.info(
                "Security: Person arriving %s — would add to expected arrivals "
                "(disabled by config)",
                person_entity,
            )

    # =========================================================================
    # Service handlers
    # =========================================================================

    async def handle_arm(self, armed_state: str, *, source: str = "manual") -> None:
        """Handle security_arm service call.

        A-H2 fix-up: ``source`` distinguishes manual (UI/service) invocations
        from the auto-follow fire path. Manual invocations stamp the current
        house_state so a subsequent auto-follow fire against the SAME
        house_state is suppressed as ``manual_hold``.
        """
        try:
            new_state = ArmedState(armed_state)
        except ValueError:
            _LOGGER.warning("Invalid armed state: %s", armed_state)
            return

        if source == "manual":
            self._stamp_manual_action()

        old_state = self._armed_state
        self._armed_state = new_state
        _LOGGER.info("Armed state changed: %s → %s", old_state.value, new_state.value)

        # Sync to alarm panel if coupled
        if self._alarm_panel_entity:
            service = _ARMED_TO_ALARM_SERVICE.get(new_state)
            if service:
                self._syncing_alarm_panel = True
                try:
                    await self.hass.services.async_call(
                        "alarm_control_panel",
                        service,
                        {"entity_id": self._alarm_panel_entity},
                        blocking=True,
                    )
                finally:
                    self._syncing_alarm_panel = False

        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

    async def handle_disarm(self, *, source: str = "manual") -> None:
        """Handle security_disarm service call.

        A-H2 fix-up: see ``handle_arm`` for the ``source`` semantics.
        """
        if source == "manual":
            self._stamp_manual_action()

        old_state = self._armed_state
        self._armed_state = ArmedState.DISARMED
        self._active_alert = False
        self._alert_details = {}
        _LOGGER.info("Disarmed (was %s)", old_state.value)

        if self._alarm_panel_entity:
            self._syncing_alarm_panel = True
            try:
                await self.hass.services.async_call(
                    "alarm_control_panel",
                    "alarm_disarm",
                    {"entity_id": self._alarm_panel_entity},
                    blocking=True,
                )
            finally:
                self._syncing_alarm_panel = False

        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

    def handle_authorize_guest(
        self, person_name: str, expires_hours: float = 24
    ) -> None:
        """Handle authorize_guest service call."""
        self._sanction_checker.authorize_guest(person_name, expires_hours)
        _LOGGER.info("Guest authorized: %s for %.1f hours", person_name, expires_hours)

    def handle_add_expected_arrival(
        self, person_id: str, window_minutes: int = 30
    ) -> None:
        """Handle add_expected_arrival service call."""
        self._sanction_checker.add_expected_arrival(person_id, window_minutes)
        _LOGGER.info(
            "Expected arrival: %s within %d minutes", person_id, window_minutes
        )

    # =========================================================================
    # Public status methods (for sensors)
    # =========================================================================

    def get_arrivals_snapshot(self) -> dict[str, Any]:
        """Return expected arrivals and authorized guests for sensor exposure."""
        arrivals = self._sanction_checker.get_expected_arrivals_snapshot()
        guests = self._sanction_checker.get_authorized_guests_snapshot()
        return {
            "expected_arrivals": arrivals,
            "expected_count": len(arrivals),
            "authorized_guests": guests,
            "guest_count": len(guests),
        }

    @property
    def delegate_lights_to_nm(self) -> bool:
        """Return whether light control is delegated to Notification Manager."""
        return self._delegate_lights_to_nm

    @delegate_lights_to_nm.setter
    def delegate_lights_to_nm(self, value: bool) -> None:
        """Set whether light control is delegated to Notification Manager."""
        self._delegate_lights_to_nm = value

    @property
    def auto_follow_house_state(self) -> bool:
        """Return whether Security auto-follows house-state transitions.

        B-H1 fix-up: public accessor so ``CoordinatorManager`` and other
        callers do NOT need to reach into the private
        ``_auto_follow_house_state`` attribute.
        """
        return self._auto_follow_house_state

    def _stamp_manual_action(self) -> None:
        """Stamp the current house_state as a manual-hold anchor (A-H2).

        Read from the CoordinatorManager's house state machine. Failures
        are non-fatal — stamp with None (which disables the hold) rather
        than crashing the arm/disarm path.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                self._manual_action_house_state = None
                return
            hs = getattr(manager, "house_state", None)
            self._manual_action_house_state = (
                str(hs) if hs is not None else None
            )
            _LOGGER.debug(
                "Security manual-hold stamp set: house_state=%s",
                self._manual_action_house_state,
            )
        except Exception:  # noqa: BLE001
            self._manual_action_house_state = None

    @property
    def armed_state(self) -> ArmedState:
        """Return the current armed state."""
        return self._armed_state

    @property
    def active_alert(self) -> bool:
        """Return whether an alert is active."""
        return self._active_alert

    @property
    def alert_details(self) -> dict[str, Any]:
        """Return current alert details."""
        return self._alert_details

    @property
    def last_entry_event(self) -> dict[str, Any]:
        """Return last entry event data."""
        return self._last_entry_event

    @property
    def lock_compliance(self) -> dict[str, str]:
        """Return lock compliance status."""
        return self._lock_compliance

    @property
    def open_entries(self) -> dict[str, datetime]:
        """Return currently open entry sensors with their opened-at timestamps."""
        return self._open_entries

    @property
    def last_lock_sweep(self) -> dict[str, Any]:
        """Return the last lock sweep results."""
        return self._last_lock_sweep

    def get_open_entries_snapshot(self) -> dict[str, Any]:
        """Return open entries data for sensor exposure."""
        now = dt_util.utcnow()
        entries = []
        for entity_id, opened_at in self._open_entries.items():
            duration_s = (now - opened_at).total_seconds()
            entries.append({
                "entity_id": entity_id,
                "opened_at": opened_at.isoformat(),
                "open_minutes": round(duration_s / 60, 1),
            })
        return {
            "count": len(self._open_entries),
            "entries": entries,
        }

    def get_security_status(self) -> str:
        """Return overall security status string."""
        if self._active_alert:
            return "alert"
        if self._armed_state == ArmedState.DISARMED:
            return "disarmed"
        return "armed"

    def get_security_aggregator_state(self) -> dict[str, Any]:
        """Return locks + cameras roll-up for SecurityAggregatorSensor.

        v4.6.9 D2: Enumerates lock.* entities from _lock_entities and
        camera.* entities from _camera_entities (both come from config, set
        in __init__).  Live per-entity state is read from the HA state machine
        at call time — no caching.

        Returns a dict with keys:
          status: str — armed | disarmed | partial | alert  (StrEnum value)
          locks_total, locks_locked, locks_unlocked, locks_jammed: int
          cameras_total, cameras_streaming, cameras_idle, cameras_offline: int
          last_state_change_iso: str | None  (UTC ISO 8601)

        Observation mode does NOT suppress this method (Bug Class #23) — the
        dashboard must reflect reality even when actions are gated.
        """
        # --- Lock enumeration ---
        locks_total = len(self._lock_entities)
        locks_locked = 0
        locks_unlocked = 0
        locks_jammed = 0

        lock_last_changed: datetime | None = None
        for entity_id in self._lock_entities:
            try:
                state = self.hass.states.get(entity_id)
            except Exception:
                state = None
            if state is None:
                locks_jammed += 1
                continue
            s = state.state
            if s == "locked":
                locks_locked += 1
            elif s == "unlocked":
                locks_unlocked += 1
            else:
                # jammed, unavailable, unknown — all count as jammed
                locks_jammed += 1
            try:
                lc = state.last_changed
                if lc is not None:
                    if lock_last_changed is None or lc > lock_last_changed:
                        lock_last_changed = lc
            except Exception:
                pass

        # --- Camera enumeration ---
        cameras_total = len(self._camera_entities)
        cameras_streaming = 0
        cameras_idle = 0
        cameras_offline = 0

        camera_last_changed: datetime | None = None
        for entity_id in self._camera_entities:
            try:
                state = self.hass.states.get(entity_id)
            except Exception:
                state = None
            if state is None:
                cameras_offline += 1
                continue
            s = state.state
            if s == "streaming":
                cameras_streaming += 1
            elif s in ("unavailable", "unknown"):
                cameras_offline += 1
            else:
                # idle, recording, or any other active-but-not-streaming state
                cameras_idle += 1
            try:
                lc = state.last_changed
                if lc is not None:
                    if camera_last_changed is None or lc > camera_last_changed:
                        camera_last_changed = lc
            except Exception:
                pass

        # --- last_state_change_iso: most recent across locks + cameras ---
        candidates = [t for t in (lock_last_changed, camera_last_changed) if t is not None]
        if candidates:
            most_recent = max(candidates)
            try:
                last_state_change_iso: str | None = most_recent.isoformat()
            except Exception:
                last_state_change_iso = None
        else:
            last_state_change_iso = None

        # --- Overall status computation ---
        # Priority order: alert > armed > partial > disarmed
        if locks_jammed > 0 or self._active_alert:
            status = _SecurityAggStatus.ALERT
        elif locks_total == 0 and cameras_total == 0:
            status = _SecurityAggStatus.DISARMED
        elif locks_locked == locks_total and cameras_streaming >= 1:
            status = _SecurityAggStatus.ARMED
        elif locks_locked > 0 or cameras_streaming > 0:
            status = _SecurityAggStatus.PARTIAL
        else:
            status = _SecurityAggStatus.DISARMED

        _LOGGER.debug(
            "Security aggregator: status=%s locks=%d/%d cameras=%d/%d streaming",
            status.value, locks_locked, locks_total, cameras_streaming, cameras_total,
        )

        return {
            "status": status.value,
            "locks_total": locks_total,
            "locks_locked": locks_locked,
            "locks_unlocked": locks_unlocked,
            "locks_jammed": locks_jammed,
            "cameras_total": cameras_total,
            "cameras_streaming": cameras_streaming,
            "cameras_idle": cameras_idle,
            "cameras_offline": cameras_offline,
            "last_state_change_iso": last_state_change_iso,
        }

    def get_compliance_summary(self) -> dict[str, Any]:
        """Return lock compliance summary."""
        total = len(self._lock_entities) + len(self._garage_entities)
        locked = sum(
            1
            for v in self._lock_compliance.values()
            if v in ("locked", "closed")
        )
        return {
            "total_devices": total,
            "compliant": locked,
            "non_compliant": total - locked,
            "compliance_rate": round(locked / total * 100, 1) if total > 0 else 100.0,
            "last_check": dt_util.utcnow().isoformat(),
            "checks_today": self._lock_checks_today.value,
        }

    def get_diagnostics_status(self) -> str:
        """Return diagnostics health status."""
        if self.anomaly_detector is None:
            return "degraded"
        return "healthy"

    def get_anomaly_status(self) -> str:
        """Return anomaly status string."""
        if self.anomaly_detector is None:
            return "not_configured"
        learning = self.anomaly_detector.get_learning_status()
        if hasattr(learning, "value") and learning.value in (
            "insufficient_data",
            "learning",
        ):
            return learning.value
        return self.anomaly_detector.get_worst_severity().value

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _maybe_reset_daily_counters(self) -> None:
        """Force a rollover check on the DailyCounter primitives.

        Kept for backward compatibility; counters roll over lazily on
        access so this is a no-op in the steady state.
        """
        self._alerts_today.rollover_if_needed()
        self._lock_checks_today.rollover_if_needed()
